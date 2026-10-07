from django.db import migrations,models

class Migration(migrations.Migration):
    dependencies=[('app','0002_import_decisions')]
    operations=[
        migrations.AddField(model_name='issuedisposition',name='due_date',field=models.DateField(blank=True,null=True)),
        migrations.AddField(model_name='issuedisposition',name='version',field=models.PositiveIntegerField(default=1)),
    ]
