# syntax=docker/dockerfile:1

# Node 22 matches what CI builds on (.github/workflows/ci.yml).
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` installs exactly the lockfile, and fails if it disagrees with
# package.json — the Node equivalent of `uv sync --locked` on the API side.
RUN npm ci


FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so this
# is a build argument rather than a runtime environment variable — setting it in
# `environment:` would do nothing at all.
#
# It defaults to localhost because **the browser resolves it, not the container**.
# `http://api:8000` works between services on the compose network and fails in
# every browser, which is exactly the kind of mistake that surfaces as an opaque
# CORS or DNS error rather than as a wrong URL.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

RUN npm run build


FROM node:22-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: "standalone"` in next.config.ts produces a server bundle carrying only
# the dependencies it actually reaches, so no node_modules is copied here.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
# No `public/` COPY: this project has no static assets directory, and COPY fails
# on a path that does not exist rather than skipping it.

USER node
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
