FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY index.html vite.config.js ./
COPY public/ public/
COPY src/ src/
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Ensure the static assets are world-readable: COPY preserves source perms, and
# any owner-only files (e.g. 600 images) would otherwise 403 for the nginx user.
RUN chmod -R a+rX /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
