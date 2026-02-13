from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tms", "0010_load_load_status_idx_load_load_disp_status_idx_and_more"),
    ]

    operations = [
        TrigramExtension(),
    ]
    
