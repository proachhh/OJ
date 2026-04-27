# submission/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from submission.models import Submission
from submission.tasks import sync_submission_to_neo4j
from knowledge_graph.tasks import update_user_mastery

@receiver(post_save, sender=Submission)
def submission_post_save(sender, instance, created, **kwargs):
    if created:
        sync_submission_to_neo4j.send(str(instance.id))
        update_user_mastery.send(instance.user_id)