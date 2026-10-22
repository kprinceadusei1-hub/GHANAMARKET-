from django.db import migrations


def seed(apps, schema_editor):
    DeliveryOption = apps.get_model("commerce", "DeliveryOption")
    if not DeliveryOption.objects.exists():
        DeliveryOption.objects.create(
            name="Collect from seller", kind="pickup", fee=0, requires_address=False, position=0,
            description="Arrange a safe, public meeting point with the seller after payment.",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("commerce", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
