FROM node:15.9.0
WORKDIR /app
COPY ../ .
RUN npm install

CMD ["npm", "run", "prod"]