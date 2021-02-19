FROM node:15.9.0
WORKDIR /app
COPY package.json .
RUN npm install
# COPY . .

COPY package.json ./package.json
COPY tailwind.config.js ./tailwind.config.js
COPY webpack.config.js ./webpack.config.js

CMD ["npm", "run", "dev"]