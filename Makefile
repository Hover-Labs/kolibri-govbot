build-docker:
	docker build -t kolibri-votebot .

bash:
	docker run --rm -it -v $$(pwd)/:/shared --workdir /shared kolibri-votebot bash

run:
	docker run --rm -it -e SENTRY_DSN=$(SENTRY_DSN) -e DISCORD_WEBHOOK=$(DISCORD_WEBHOOK) -v $$(pwd):/shared --workdir /shared kolibri-votebot python3 /shared/main.py
