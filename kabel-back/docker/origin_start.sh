docker run -d \
  --name labelu \
  --network labelu-net \
  -p 8082:8000 \
  -e PASSWORD_SECRET_KEY='kaifang' \
  -e DATABASE_URL='mysql+pymysql://root:root@labelu-mysql:3306/labelu?charset=utf8mb4' \
  labelu:mysql
