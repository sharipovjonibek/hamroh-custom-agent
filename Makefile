build:
	docker build -t hamroh-base ./framework
	docker compose build agent

auth: build
	docker compose run --rm codex-auth

auth-status: build
	docker compose run --rm codex-auth python -m hamroh.codex_login --status

up: build
	docker compose up -d agent

update:
	./scripts/commit-and-push.sh
	git pull --rebase
	git submodule sync -- framework
	git submodule update --init --remote framework
	git diff --quiet framework || (git add framework && git commit -m "bump framework [skip ci]")
	git push
	$(MAKE) up

logs:
	docker compose logs -f agent

down:
	docker compose down

railway-auth-export:
	./scripts/export-railway-auth.sh

railway-auth-upload:
	./scripts/upload-railway-auth.sh

railway-auth-retire-local:
	./scripts/retire-local-auth.sh

railway-smoke:
	docker build -f Dockerfile.railway -t shahnoza-agent:railway-test .
	./tests/smoke_railway_image.sh

.PHONY: build auth auth-status up update logs down railway-auth-export railway-auth-upload railway-auth-retire-local railway-smoke
