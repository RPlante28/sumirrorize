# Playwright's image ships Chromium and the system libraries it needs. Keep its version
# in step with the playwright package in package-lock.json.
FROM mcr.microsoft.com/playwright:v1.65.1-noble AS build
WORKDIR /app
COPY package.json package-lock.json ./
# --ignore-scripts skips the postinstall browser download; the image already has one.
RUN npm ci --ignore-scripts
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM mcr.microsoft.com/playwright:v1.65.1-noble
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY --from=build /app/dist ./dist
COPY public ./public
USER pwuser
EXPOSE 3100
CMD ["node", "dist/index.js"]
