from django.shortcuts import render, redirect, get_object_or_404
from .forms import MakaleYuklemeForm, MakaleForm, MakaleMesajForm, HakemOlusturForm, DegerlendirmeForm
from .models import Makale, AnonymizedMakale, HakemAtama, Hakem, Degerlendirme
from .utils import belirle_makale_alanlari_nlp, hakem_atama, anonymize_names_in_pdf, extract_keywords_with_nlp, extract_text_from_pdf, decrypt_anonymized_pdf
from django.urls import reverse
from django.conf import settings
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseRedirect
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io, os

def index(request):
    return render(request, 'makale/index.html')

def makale_yukle(request):
    if request.method == 'POST':
        form = MakaleYuklemeForm(request.POST, request.FILES)
        if form.is_valid():
            makale = form.save(commit=False)
            uploaded_file = request.FILES['pdf_dosya']
            makale.save()

            extension = uploaded_file.name.split('.')[-1]
            new_filename = f"makale_{makale.id}_{makale.baslik.replace(' ', '_')}.{extension}"
            makale.pdf_dosya.save(new_filename, uploaded_file, save=True)

            text = extract_text_from_pdf(makale.pdf_dosya.name)

            keywords = extract_keywords_with_nlp(text)
            makale.anahtar_kelimeler = ", ".join(keywords)

            alanlar = belirle_makale_alanlari_nlp(text)
            makale.alanlar.set(alanlar)

            makale.save()

            return render(request, 'makale/yukleme_basarili.html', {'makale': makale})
    else:
        form = MakaleYuklemeForm()

    return render(request, 'makale/makale_yukle.html', {'form': form})


def editor_paneli(request):
    makaleler = Makale.objects.all().order_by('-yuklenme_tarihi')  # Son yüklenen ilk görünsün
    return render(request, 'makale/editor_paneli.html', {'makaleler': makaleler})

def hakem_paneli(request):
    username = request.session.get('hakem_username')
    hakem = Hakem.objects.filter(kullanici__username=username).first() if username else None

    if not hakem:
        return render(request, 'makale/hakem_paneli.html', {
            'atamalar': [],
            'hakem': None
        })
    
    atamalar = HakemAtama.objects.filter(hakem=hakem).order_by('-atama_tarihi')
    for atama in atamalar:
        atama.anonim_pdf = AnonymizedMakale.objects.filter(orijinal_makale=atama.makale).first()

    return render(request, 'makale/hakem_paneli.html', {'atamalar': atamalar, 'hakem': hakem})

def hakem_giris(request):
    if request.method == "POST":
        username = request.POST.get("username")
        hakem = Hakem.objects.filter(kullanici__username=username).first()
        if hakem:
            request.session['hakem_username'] = username
            return redirect('hakem_paneli')
    hakemler = Hakem.objects.all()
    return render(request, 'makale/hakem_giris.html', {'hakemler': hakemler})

def hakem_olustur(request):
    if request.method == 'POST':
        form = HakemOlusturForm(request.POST)
        if form.is_valid():
            form.save()
        return redirect('editor_paneli')
    else:
        form = HakemOlusturForm()
    
    return render(request, 'makale/hakem_olustur.html', {'form': form})

def makale_detay(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    anonim_makale = AnonymizedMakale.objects.filter(orijinal_makale=makale).first()
    hakem_atama = HakemAtama.objects.filter(makale=makale).first()
    uygun_hakemler = Hakem.objects.filter(ilgi_alanlari__in=makale.alanlar.all()).distinct()
    degerlendirme = Degerlendirme.objects.filter(makale=makale).first()

    # POST ile bilgi türü güncellenirse
    if request.method == 'POST' and 'bilgi_turleri' in request.POST:
        selected = request.POST.getlist('bilgi_turleri')
        if anonim_makale:
            anonim_makale.secilen_bilgi_turleri = selected
            anonim_makale.save()

    return render(request, 'makale/makale_detay.html', {
        'makale': makale,
        'anonim_makale': anonim_makale,
        'hakem_atama': hakem_atama,
        'uygun_hakemler': uygun_hakemler,
        'degerlendirme': degerlendirme
})


def anonimlestir(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)

    input_path = makale.pdf_dosya.name
    output_relative_path = f"anonim_makaleler/anonim_{makale.id}_{makale.baslik.replace(' ', '_')}.pdf"
    encrypted_names_dict = {}

    # 🔄 Editörün seçtiği bilgi türlerini al
    secilen_turler = request.POST.getlist("bilgi_turleri")
    if not secilen_turler:
        secilen_turler = ["PERSON", "ORG", "EMAIL", "GPE", "LOC", "IMAGE"]  # Default

    anonymize_names_in_pdf(
        input_path,
        output_relative_path,
        encrypted_names_dict,
        secilen_turler,
        makale.id
    )

    anonim_makale, created = AnonymizedMakale.objects.get_or_create(
        orijinal_makale=makale,
        defaults={
            "anonim_makale_pdf": output_relative_path,
            "sifreli_veriler": encrypted_names_dict,
            "secilen_bilgi_turleri": secilen_turler
        }
    )

    if not created:
        anonim_makale.anonim_makale_pdf.name = output_relative_path
        anonim_makale.sifreli_veriler = encrypted_names_dict
        anonim_makale.secilen_bilgi_turleri = secilen_turler
        anonim_makale.save()

    return redirect('makale_detay', makale_id=makale.id)


def hakem_ata(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)

    if request.method == 'POST':
        hakem_id = request.POST.get('hakem_id')
        if hakem_id:
            hakem = get_object_or_404(Hakem, id=hakem_id)

            # Daha önce atama varsa tekrar atama yapma
            if not HakemAtama.objects.filter(makale=makale).exists():
                HakemAtama.objects.create(makale=makale, hakem=hakem)
                messages.success(request, f"Hakem '{hakem.kullanici.username}' başarıyla atandı.")
            else:
                messages.warning(request, "Bu makaleye zaten bir hakem atanmış.")

    return redirect('makale_detay', makale_id=makale.id)

def makale_durum_guncelle(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    yeni_durum = request.GET.get('durum')

    if yeni_durum in ['Beklemede', 'Değerlendiriliyor', 'Tamamlandı']:
        makale.durum = yeni_durum
        makale.save()

    return redirect('makale_detay', makale_id=makale.id)

def makale_sorgula(request):
    return render(request, 'makale/makale_sorgula.html')

def makale_sorgu_detay(request):
    sorgu_no = request.GET.get('sorgu_no', '')  # URL'den sorgu numarasını al
    makale = Makale.objects.filter(takip_numarasi=sorgu_no).first()  # Takip numarasına göre makale bul

    if not makale:
        return render(request, 'makale/makale_sorgu_detay.html', {'error': 'Makale bulunamadı.'})

    return render(request, 'makale/makale_sorgu_detay.html', {'makale': makale})

def makale_duzenle(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)  # Makale bulunamazsa 404 hatası ver

    if request.method == "POST":
        form = MakaleForm(request.POST, request.FILES, instance=makale)
        if form.is_valid():
            form.save()
            return redirect(f"{reverse('makale_sorgu_detay')}?sorgu_no={makale.takip_numarasi}")  # Güncelleme sonrası yönlendirme

    else:
        form = MakaleForm(instance=makale)  # Mevcut makale bilgileri formda görünsün

    return render(request, 'makale/makale_duzenle.html', {'form': form, 'makale': makale})

def makale_mesajlar(request, makale_id, rol):
    makale = get_object_or_404(Makale, id=makale_id)
    mesajlar = makale.mesajlar.order_by('tarih')  # Mesajları tarihe göre sırala
    form = MakaleMesajForm()

    if request.method == "POST":
        form = MakaleMesajForm(request.POST)
        if form.is_valid():
            mesaj = form.save(commit=False)  # Formdan mesaj objesi oluştur
            mesaj.makale = makale  # Mesajı ilgili makaleye bağla

            # Yazar mı editör mü belirle
            if rol == "yazar":
                mesaj.gonderen = 'Yazar'
            elif rol == "editor":
                mesaj.gonderen = 'Editör'
            else:
                return redirect('makale_mesajlar', makale_id=makale.id)  # Geçersiz rol varsa yönlendir

            mesaj.save()  # Mesajı veritabanına kaydet

            # Doğru URL'ye yönlendir
            if rol == "yazar":
                return redirect('makale_mesajlar', makale_id=makale.id)
            elif rol == "editor":
                return redirect('editor_makale_mesajlar', makale_id=makale.id)

    return render(request, 'makale/makale_mesajlar.html', {
        'makale': makale,
        'mesajlar': mesajlar,
        'form': form,
        'rol': rol  # HTML tarafında da rolü göstermek için
    })

def degerlendirme_ekle(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    hakem = Hakem.objects.filter(kullanici__username=request.session.get("hakem_username")).first()

    if not hakem:
        messages.error(request, "Hakem bulunamadı.")
        return redirect('hakem_giris')

    if request.method == "POST":
        yorum = request.POST.get("yorum")
        dosya = request.FILES.get("pdf_dosya")

        Degerlendirme.objects.create(
            hakem=hakem,
            makale=makale,
            yorum=yorum,
            pdf_dosya=dosya,
            tarih=timezone.now()
        )

        # HakemAtama'da değerlendirme yapıldı olarak işaretle
        atama = HakemAtama.objects.filter(hakem=hakem, makale=makale).first()
        if atama:
            atama.degerlendirme_yapildi = True
            atama.save()

        messages.success(request, "Değerlendirmeniz kaydedildi.")
        return redirect('hakem_paneli')

    return render(request, 'makale/hakem_degerlendir.html', {
        'makale': makale
    })

def makale_sonucu_olustur(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    anonim_makale = AnonymizedMakale.objects.filter(orijinal_makale=makale).first()
    degerlendirme = Degerlendirme.objects.filter(makale=makale).first()

    if not anonim_makale or not degerlendirme:
        messages.error(request, "Eksik veri: Anonimleştirilmiş belge veya değerlendirme bulunamadı.")
        return redirect('makale_detay', makale_id=makale.id)

    # 1. Anonim PDF'i deşifre ederek orijinale döndür
    anonim_pdf_path = os.path.join(settings.MEDIA_ROOT, anonim_makale.anonim_makale_pdf.name)
    decrypted_pdf_path = os.path.join(settings.MEDIA_ROOT, f"temp_decrypted_{makale.id}.pdf")

    decrypt_anonymized_pdf(
        anonim_pdf_path,
        decrypted_pdf_path,
        anonim_makale.sifreli_veriler,
        settings.MEDIA_ROOT,
        "original_images"
    )

    # 2. Sonuç PDF dosya yolu
    sonuc_relative_path = f"sonuclar/sonuc_{makale.id}.pdf"
    sonuc_pdf_path = os.path.join(settings.MEDIA_ROOT, sonuc_relative_path)
    os.makedirs(os.path.dirname(sonuc_pdf_path), exist_ok=True)

    # 3. PDFWriter ile sayfaları birleştir
    output = PdfWriter()

    # Orijinal PDF (deşifre edilmiş) ekle
    with open(decrypted_pdf_path, "rb") as f:
        reader = PdfReader(f)
        for page in reader.pages:
            output.add_page(page)

    # Hakem yorumu sayfası oluştur
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    can.setFont("Helvetica", 12)
    can.drawString(100, 800, "📝 Hakem Yorumu:")
    text_obj = can.beginText(100, 780)
    for line in degerlendirme.yorum.splitlines():
        text_obj.textLine(line)
    can.drawText(text_obj)
    can.save()
    packet.seek(0)
    yorum_reader = PdfReader(packet)
    output.add_page(yorum_reader.pages[0])

    # Ekli hakem PDF varsa ekle
    if degerlendirme.pdf_dosya:
        hakem_pdf_path = os.path.join(settings.MEDIA_ROOT, degerlendirme.pdf_dosya.name)
        if os.path.exists(hakem_pdf_path):
            with open(hakem_pdf_path, "rb") as f:
                hakem_reader = PdfReader(f)
                for page in hakem_reader.pages:
                    output.add_page(page)

    # Tüm sayfaları kaydet
    with open(sonuc_pdf_path, "wb") as f:
        output.write(f)

    # Makaleye sonuç PDF yolunu kaydet
    makale.sonuc_pdf.name = sonuc_relative_path
    makale.save()

    messages.success(request, "✅ Sonuç PDF başarıyla oluşturuldu.")
    return redirect('makale_detay', makale_id=makale.id)