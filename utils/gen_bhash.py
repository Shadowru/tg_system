#python3 -c "import bcrypt; print(bcrypt.hashpw(b'my_prometheus_password', bcrypt.gensalt()).decode())"
import bcrypt; 
print(bcrypt.hashpw(b'my_prometheus_password', bcrypt.gensalt()).decode())