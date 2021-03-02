FROM node:15.9.0
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .

CMD ["npm", "run", "prod"]