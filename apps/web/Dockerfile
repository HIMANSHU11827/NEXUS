FROM node:20-alpine AS build
WORKDIR /app/gui
COPY gui/package.json gui/package-lock.json ./
RUN npm ci
COPY gui/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/gui/dist /usr/share/nginx/html
COPY gui/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
