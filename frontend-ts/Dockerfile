# Web UI image: builds frontend-ts and serves dist/ with nginx.
# Build context is frontend-ts/. In Kubernetes the nginx config (including the
# /backend/ proxy) comes from the web-nginx ConfigMap in k8s/40-web.yaml.

FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
