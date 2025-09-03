from django.db import models
from django.contrib.auth.models import AbstractUser
import hashlib
import uuid
from django.conf import settings

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('yazar', 'Yazar'),
        ('editor', 'Editör'),
        ('hakem', 'Hakem'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='yazar')

    def __str__(self):
        return f"{self.username} - {self.role}"

class IlgiAlani(models.Model):
    KATEGORILER = [
        ('AI', 'Yapay Zeka ve Makine Öğrenimi'),
        ('HCI', 'İnsan-Bilgisayar Etkileşimi'),
        ('BIGDATA', 'Büyük Veri ve Veri Analitiği'),
        ('SECURITY', 'Siber Güvenlik'),
        ('NETWORK', 'Ağ ve Dağıtık Sistemler'),
    ]
    kategori = models.CharField(max_length=20, choices=KATEGORILER)
    isim = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.get_kategori_display()} - {self.isim}"
    
def generate_tracking_id():
    unique_id = str(uuid.uuid4())
    return hashlib.sha256(unique_id.encode()).hexdigest()[:10]

class Makale(models.Model):
    takip_numarasi = models.CharField(max_length=64, unique=True, default=generate_tracking_id)
    baslik = models.CharField(max_length=255)
    pdf_dosya = models.FileField(upload_to='makaleler/')
    yazar_email = models.EmailField()
    yuklenme_tarihi = models.DateTimeField(auto_now_add=True)
    anahtar_kelimeler = models.TextField(blank=True)
    alanlar = models.ManyToManyField(IlgiAlani, blank=True)
    durum = models.CharField(max_length=20, choices=[
        ('Beklemede', 'Beklemede'),
        ('Değerlendiriliyor', 'Değerlendiriliyor'),
        ('Tamamlandı', 'Tamamlandı')
    ], default='Beklemede')
    sonuc_pdf = models.FileField(upload_to="sonuclar/", null=True, blank=True)


    def __str__(self):
        return self.baslik

class AnonymizedMakale(models.Model):
    orijinal_makale = models.OneToOneField(Makale, on_delete=models.CASCADE, related_name='anonim_makale')
    anonim_makale_pdf = models.FileField(upload_to='anonim_makaleler/')
    sifreli_veriler = models.JSONField(null=True, blank=True)
    islenme_tarihi = models.DateTimeField(auto_now_add=True)
    hash_degeri = models.CharField(max_length=64, unique=True, blank=True)
    secilen_bilgi_turleri = models.JSONField(null=True, blank=True, default=dict)  # Yeni alan

    def save(self, *args, **kwargs):
        if not self.hash_degeri:
            self.hash_degeri = hashlib.sha256(str(self.orijinal_makale.id).encode()).hexdigest()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Anonimleştirilmiş: {self.orijinal_makale.baslik}"

class Hakem(models.Model):
    kullanici = models.OneToOneField(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'hakem'})
    ilgi_alanlari = models.ManyToManyField(IlgiAlani, blank=True)

    def __str__(self):
        return f"Hakem: {self.kullanici.username}"
    
class HakemAtama(models.Model):
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE)
    hakem = models.ForeignKey(Hakem, on_delete=models.CASCADE)
    atama_tarihi = models.DateTimeField(auto_now_add=True)
    degerlendirme_yapildi = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.makale.baslik} - {self.hakem.kullanici.username}"

class Degerlendirme(models.Model):
    hakem = models.ForeignKey(Hakem, on_delete=models.CASCADE)
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE)
    yorum = models.TextField()
    pdf_dosya = models.FileField(upload_to='degerlendirmeler/', blank=True, null=True)
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.makale.baslik} - {self.hakem.kullanici.username}"

class Log(models.Model):
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE)
    kullanici = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    islem = models.TextField()
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tarih} - {self.kullanici.username} - {self.islem}"
    
class MakaleMesaj(models.Model):
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE, related_name='mesajlar')
    gonderen = models.CharField(max_length=10, choices=[('Yazar', 'Yazar'), ('Editör', 'Editör')])
    icerik = models.TextField()
    tarih = models.DateTimeField(auto_now_add=True)

    def kimden(self):
        if self.gonderen == "Yazar":
            return "Yazar"
        elif self.gonderen == "Editör":
            return "Editör"
        else:
            return "Bilinmeyen"

    def __str__(self):
        return f"{self.kimden()} - {self.tarih.strftime('%Y-%m-%d %H:%M')}"