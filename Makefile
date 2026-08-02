.PHONY: up down logs rebuild test demo

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose build --no-cache

demo:
	DEMO_MODE=true docker compose up -d --build

test:
	cd backend && python -m pytest
	cd frontend && npm test && npm run build
