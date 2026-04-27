# knowledge_graph/management/commands/graph_self_learning.py
from django.core.management.base import BaseCommand
from knowledge_graph.tasks import run_full_graph_learning

class Command(BaseCommand):
    help = 'Run knowledge graph self-learning process'

    def handle(self, *args, **options):
        self.stdout.write('Starting knowledge graph self-learning...')
        run_full_graph_learning.send()
        self.stdout.write(self.style.SUCCESS('Self-learning task dispatched successfully'))
