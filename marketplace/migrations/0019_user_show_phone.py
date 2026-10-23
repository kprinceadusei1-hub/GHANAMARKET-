from django.db import migrations, models


def sellers_show_phone(apps, schema_editor):
    # Buyers can now call or text sellers; sellers can switch this off in Account settings.
    apps.get_model("marketplace", "User").objects.filter(role="seller").update(show_phone=True)


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0018_user_whatsapp_contact")]

    operations = [
        migrations.RenameField(model_name="user", old_name="whatsapp_contact", new_name="show_phone"),
        migrations.AlterField(
            model_name="user",
            name="show_phone",
            field=models.BooleanField(default=True, help_text="Signed-in buyers can tap “Show phone number” on your ads to call, text or WhatsApp you."),
        ),
        migrations.RunPython(sellers_show_phone, migrations.RunPython.noop),
    ]
