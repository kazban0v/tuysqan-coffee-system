"""Remove an unconfirmed product from sale without deleting order history.

Reversing this migration deliberately does not return the product to sale.
"""
from django.db import migrations


def retire_classic_shakshuka(apps, schema_editor):
    MenuItem = apps.get_model('core', 'MenuItem')
    MenuItem.objects.using(schema_editor.connection.alias).filter(
        slug='classic-shakshuka',
    ).update(available=False)


class Migration(migrations.Migration):
    dependencies = [('core', '0011_single_use_loyalty_and_residential')]
    operations = [migrations.RunPython(retire_classic_shakshuka, migrations.RunPython.noop)]
