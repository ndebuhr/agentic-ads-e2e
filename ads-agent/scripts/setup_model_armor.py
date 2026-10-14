"""Creates or updates the Model Armor template the agent screens with.

Every filter is set to its least sensitive setting, so only high-confidence
matches block: the four responsible-AI filters and prompt injection and
jailbreak at HIGH confidence, plus malicious URL detection. Sensitive Data
Protection is off, since ad account data isn't personal data.

    uv run scripts/setup_model_armor.py --project PROJECT [--location us-central1] [--template ads-agent]

Uses Application Default Credentials. Needs the Model Armor API enabled in the
project and the Model Armor Admin role (roles/modelarmor.admin) for setup;
the agent itself needs Model Armor User (roles/modelarmor.user).
"""
import argparse

from google.api_core import exceptions
from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1 as m
from google.protobuf import field_mask_pb2

RAI_FILTERS = ["HATE_SPEECH", "HARASSMENT", "SEXUALLY_EXPLICIT", "DANGEROUS"]


def filter_config() -> m.FilterConfig:
    return m.FilterConfig(
        rai_settings=m.RaiFilterSettings(rai_filters=[
            m.RaiFilterSettings.RaiFilter(filter_type=getattr(m.RaiFilterType, f), confidence_level=m.DetectionConfidenceLevel.HIGH)
            for f in RAI_FILTERS]),
        pi_and_jailbreak_filter_settings=m.PiAndJailbreakFilterSettings(
            filter_enforcement=m.PiAndJailbreakFilterSettings.PiAndJailbreakFilterEnforcement.ENABLED,
            confidence_level=m.DetectionConfidenceLevel.HIGH),
        malicious_uri_filter_settings=m.MaliciousUriFilterSettings(
            filter_enforcement=m.MaliciousUriFilterSettings.MaliciousUriFilterEnforcement.ENABLED),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--location", default="us-central1")
    p.add_argument("--template", default="ads-agent")
    a = p.parse_args()

    client = m.ModelArmorClient(client_options=ClientOptions(api_endpoint=f"modelarmor.{a.location}.rep.googleapis.com"))
    parent = f"projects/{a.project}/locations/{a.location}"
    name = f"{parent}/templates/{a.template}"
    template = m.Template(name=name, filter_config=filter_config())
    try:
        client.get_template(name=name)
        client.update_template(template=template, update_mask=field_mask_pb2.FieldMask(paths=["filter_config"]))
        print(f"Updated {name}")
    except exceptions.NotFound:
        client.create_template(parent=parent, template_id=a.template, template=template)
        print(f"Created {name}")
    except exceptions.PermissionDenied as e:
        raise SystemExit(f"{e.message}\nIf the API is off, enable it with: "
                         f"gcloud services enable modelarmor.googleapis.com --project {a.project}")
    print(f"Set in .env:\nADS_AGENT_MODEL_ARMOR_TEMPLATE={name}")


if __name__ == "__main__":
    main()
