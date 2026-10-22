from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0017_seller_approval")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="whatsapp_contact",
            field=models.BooleanField(
                default=False, help_text="Show a WhatsApp button on this person's listings (reveals their phone number).",
            ),
        ),
    ]
