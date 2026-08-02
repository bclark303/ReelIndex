# Build Validation

Validation performed in the development workspace on July 30, 2026.

## Passed

- Python source compilation for the complete backend
- Five backend unit tests covering title/year/edition parsing, resolution labels, title sorting, normalized grouping keys, and credential encryption
- FastAPI startup and API smoke tests for health, statistics, movie listing, movie details, sources, and diagnostics
- End-to-end filesystem inventory test using a generated 1280×720 H.264/AAC MP4
  - Connection test succeeded
  - Background scan completed
  - ffprobe metadata was persisted and returned through the movie API
  - Extended-edition recognition succeeded
- Incremental scan test
  - First scan analyzed the file
  - Second unchanged scan reported one cached file and zero analyzed files
- Movie filters for multiple versions and probe errors returned valid responses
- Docker Compose YAML parsed successfully
- Frontend TypeScript source passed structural type/syntax validation with TypeScript 5.8 using temporary module declarations

## Deferred to Docker installation test

The workspace does not provide a Docker daemon, so container images and Compose startup could not be executed here.

The workspace's internal npm registry also did not provide public React/Vite packages, so the real `npm install`, Vitest run, and Vite production bundle must run during the Docker build on a machine with normal package-registry access. No dependencies are vendored into the project.

Recommended first test:

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```
