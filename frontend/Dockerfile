# syntax=docker/dockerfile:1
# Frontend — AI Agent Failure Memory (Next.js 16)
#
# Multi-stage build: lockfile-exact install -> production build -> minimal
# non-root production server (`next start`, NOT `next dev`).
# Linux containers only (linux/amd64 + linux/arm64); no host Node.js required.
#
# NEXT_PUBLIC_* values are inlined into the browser bundle at BUILD time and
# must be the URL the user's browser uses to reach the backend (host-mapped
# port), never a Docker-internal hostname such as "backend".

# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #
FROM node:24.22.0-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

# --------------------------------------------------------------------------- #
# Builder stage — full install (build tooling) + `next build`
# --------------------------------------------------------------------------- #
FROM base AS builder

COPY package.json package-lock.json ./
# NODE_ENV deliberately unset here: npm omits devDependencies (eslint,
# typescript, ...) when NODE_ENV=production, and the build needs them.
RUN npm ci --ignore-scripts

COPY . .

# Browser-facing API URL (public), baked in at build time. compose.yaml sets
# this from BACKEND_PORT so it matches the published host port.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

# The build-time cache (.next/cache) is useless in the runtime image (24+ MB).
RUN npm run build && rm -rf .next/cache

# --------------------------------------------------------------------------- #
# Production runner
# --------------------------------------------------------------------------- #
FROM base AS production
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

# Standalone output contains only the traced production dependencies needed by
# the server, avoiding the full production node_modules tree.
COPY --from=builder --chown=appuser:appuser /app/.next/standalone ./
COPY --from=builder --chown=appuser:appuser /app/.next/static ./.next/static
COPY --from=builder --chown=appuser:appuser /app/public ./public

USER appuser

EXPOSE 3000

# Container health check against the dashboard root.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000', (r) => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

# Production server (next start defaults to 0.0.0.0; bound explicitly anyway).
# Exec-form `node` (not `npm start`) so signals are handled by the server.
CMD ["node", "server.js"]