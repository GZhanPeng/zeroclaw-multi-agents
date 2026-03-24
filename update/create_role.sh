#!/usr/bin/env bash
set -e

ROLE="$1"
BASE_DIR=".zeroclaw/workspace/character"
ROLE_DIR="$BASE_DIR/$ROLE"

if [[ -z "$ROLE" ]]; then
  echo "[ERR] 用法: ./create_role.sh <role_name>"
  exit 1
fi

if [[ -d "$ROLE_DIR" ]]; then
  echo "[ERR] 角色已存在: $ROLE"
  exit 1
fi

mkdir -p "$ROLE_DIR"

cat > "$ROLE_DIR/SOUL.md" <<EOF
# SOUL

You are the $ROLE role.

## Purpose
Describe the core purpose of this role here.

## Style
Describe the tone, constraints, and behavioral preferences here.
EOF

cat > "$ROLE_DIR/IDENTITY.md" <<EOF
# IDENTITY

Role name: $ROLE

## Responsibilities
Describe what this role is responsible for.

## Boundaries
Describe what this role should and should not do.
EOF

echo "[DONE] 已创建角色: $ROLE"
echo "  - $ROLE_DIR/SOUL.md"
echo "  - $ROLE_DIR/IDENTITY.md"