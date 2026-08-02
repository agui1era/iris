#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
create_admin=false
skip_frontend=false
production=false

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Install IRIS dependencies and create local environment files.

Options:
  --create-admin   Create the first administrator after installing
  --skip-frontend  Skip Node.js dependency installation
  --production     Install Python runtime dependencies without dev tools
  -h, --help       Show this help message
EOF
}

for argument in "$@"; do
  case "$argument" in
    --create-admin) create_admin=true ;;
    --skip-frontend) skip_frontend=true ;;
    --production) production=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $argument" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

copy_example() {
  local source_path="$1"
  local destination_path="$2"

  if [[ -e "$destination_path" ]]; then
    echo "Keeping existing ${destination_path#"$project_dir"/}"
  else
    cp "$source_path" "$destination_path"
    echo "Created ${destination_path#"$project_dir"/}"
  fi
}

if ! command_exists python3; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required. Found: $(python3 --version 2>&1)" >&2
  exit 1
fi

if ! command_exists uv; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ "$skip_frontend" == false ]]; then
  if ! command_exists node || ! command_exists npm; then
    echo "Node.js 20 or newer and npm are required for the dashboard." >&2
    exit 1
  fi

  if ! node -e 'const major = Number(process.versions.node.split(".")[0]); process.exit(major >= 20 ? 0 : 1)'; then
    echo "Node.js 20 or newer is required. Found: $(node --version 2>&1)" >&2
    exit 1
  fi
fi

cd "$project_dir"

copy_example "$project_dir/.env.example" "$project_dir/.env"
copy_example "$project_dir/frontend/.env.example" "$project_dir/frontend/.env"

echo "Installing Python dependencies..."
if [[ "$production" == true ]]; then
  uv sync --no-dev
else
  uv sync --extra dev
fi

if [[ "$skip_frontend" == false ]]; then
  echo "Installing frontend dependencies..."
  npm ci --prefix "$project_dir/frontend"
fi

if [[ "$create_admin" == true ]]; then
  if [[ ! -t 0 ]]; then
    echo "--create-admin requires an interactive terminal." >&2
    exit 1
  fi
  read -r -p "Administrator username [admin]: " admin_username
  admin_username="${admin_username:-admin}"
  uv run iris-users create --username "$admin_username" --role admin
fi

cat <<'EOF'

IRIS is installed.

Before starting it, edit .env and replace the example credentials, camera
URLs, prompts, and AUTH_JWT_SECRET.

Run these commands in separate terminals:
  uv run iris-monitor
  uv run iris-api
  cd frontend && npm run dev

Dashboard: http://localhost:5173
API:       http://localhost:8000
EOF
