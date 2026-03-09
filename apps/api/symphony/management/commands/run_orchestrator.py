from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the Symphony orchestrator loop."

    def handle(self, *args: object, **options: object) -> str | None:
        self.stdout.write(
            self.style.WARNING("Orchestrator skeleton created. Implementation is pending.")
        )
        return None
