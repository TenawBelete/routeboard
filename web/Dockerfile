# Stage 1: build the static site. Stage 2: serve it with Caddy, which also
# proxies /api to the FastAPI container and (in production) gets the HTTPS certificate.
FROM node:26-alpine AS build
WORKDIR /web
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
