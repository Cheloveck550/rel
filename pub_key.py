import base64
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

# 🔑 Вставь сюда свой PrivateKey из вывода xray x25519
priv_base64 = "-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"

# Декодируем base64.RawURLEncoding
priv_bytes = base64.urlsafe_b64decode(priv_base64 + "=" * (-len(priv_base64) % 4))

# Создаём объект приватного ключа
priv = x25519.X25519PrivateKey.from_private_bytes(priv_bytes)

# Получаем публичный ключ
pub = priv.public_key()

# Кодируем в base64.RawURLEncoding
pub_bytes = pub.public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)
pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

print("✅ PrivateKey:", priv_base64)
print("✅ PublicKey :", pub_b64)
