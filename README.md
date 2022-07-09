## FFCSA

### Migration Issues   
When running migrations, run the migrations for ffcsa_core up to 0055 `python manage.py migrate ffcsa_core 0055`
The you will need to manually enter the migration as ran into the database for 0056 `insert into django_migrations ('ffcsa_core', '0056_user', now());`
This is b/c we switched user models after already in production

#### Bootup
- Clone the project
- Checkout to `staging`
- Docker Startup
    - Development env
        - run command `docker-compose -f docker-compose-dev.yml up`
    - Staging env
      - run command `docker-compose -f docker-compose-staging.yml up`
    - Production env
      - run command `docker-compose -f docker-compose.yml up`
- Local Development Server
  - Create virtualenv with python `v3.9.10`
  - Activate virtualenv
  - Install requirements `pip install -r requirements.current.txt`
  - Import SQL file sql `mysql/ffcsa.sql` to database
  - Add `.env` to root of the project
  - Add `local_settings.py` to `ffcsa` app
  - Make migrations
    - `python manage.py migrate --fake`
    - `python manage.py migrate`
  - Install packages for front `npm install`
  - Collect all static files `python manage.py collectstatic`
  - Run servers front (VueJs) + back (Django)
    - run those 2 commandes, each of them on separate shell
      - `npm run dev` 
      - `python manage.py runserver`
  - Open `localhost:8000` on browser
  - Start Coding!

