"""
Management command to idempotently seed the Bloom pre-filter with toxic words.
"""

import asyncio
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.chat.moderation.bloom import RedisBloomBackend, get_bloom_backend
from apps.chat.moderation.seed import load_seed_tokens, seed_bloom


class Command(BaseCommand):
    help = "Idempotently seed the Bloom pre-filter Layer 2 with toxic tokens."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backend",
            type=str,
            default=None,
            help="Backend to seed: 'local' or 'redis' (default: settings.BLOOM_BACKEND).",
        )
        parser.add_argument(
            "--extras",
            type=str,
            default=None,
            help="Path to an optional additional text file with custom toxic tokens (one per line).",
        )

    def handle(self, *args, **options):
        backend_name = options.get("backend")
        extras_path = options.get("extras")

        backend = get_bloom_backend(backend_name)
        self.stdout.write(f"Target Bloom backend: {type(backend).__name__}")

        tokens = load_seed_tokens()
        if extras_path:
            p = Path(extras_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            tokens.append(line.lower())
                tokens = sorted(set(tokens))
                self.stdout.write(f"Merged extra tokens from {extras_path}")
            else:
                self.stderr.write(f"Extras file not found: {extras_path}")

        self.stdout.write(f"Seeding {len(tokens)} toxic tokens into Bloom filter...")

        async def run_seed():
            if isinstance(backend, RedisBloomBackend):
                # Check probe first
                is_alive = await backend.probe()
                if not is_alive:
                    self.stderr.write(
                        self.style.WARNING(
                            "Warning: Redis / RedisBloom probe failed. "
                            "Ensure Redis with the RedisBloom module is running."
                        )
                    )
            return await seed_bloom(backend, tokens)

        added = asyncio.run(run_seed())
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded Bloom filter ({type(backend).__name__}) with {len(tokens)} tokens ({added} new bits/entries added)."
            )
        )
