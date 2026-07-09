FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next.config.mjs resolves rewrites() at build time, so the proxy target must
# be present here. This is deliberately NOT NEXT_PUBLIC_API_URL: that var gets
# inlined into the client bundle, and "api" (the Docker service name) isn't
# resolvable from the browser — only from inside the compose network.
ARG API_PROXY_TARGET
ENV API_PROXY_TARGET=$API_PROXY_TARGET
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["npm", "start"]
