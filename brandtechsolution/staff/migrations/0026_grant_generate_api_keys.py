from django.db import migrations

CODENAME = "generate_api_keys"
LABEL = "Generate developer API keys"


def grant_to_administrator(apps, schema_editor):
    """Give the Administrator preset the new generate_api_keys capability.

    Administrator holds every capability by design. The permission row is
    created by post_migrate, so get_or_create keeps that idempotent.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="staff", model="staffcapability"
    )
    permission, _ = Permission.objects.get_or_create(
        codename=CODENAME, content_type=content_type, defaults={"name": LABEL}
    )

    group = Group.objects.filter(name="Administrator").first()
    if group is not None:
        group.permissions.add(permission)


def revoke_from_administrator(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permission = Permission.objects.filter(
        codename=CODENAME, content_type__app_label="staff"
    ).first()
    if permission is None:
        return

    group = Group.objects.filter(name="Administrator").first()
    if group is not None:
        group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0025_alter_staffcapability_options"),
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
    ]

    operations = [
        migrations.RunPython(grant_to_administrator, revoke_from_administrator),
    ]
