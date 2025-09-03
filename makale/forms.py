from django import forms
from .models import Makale, MakaleMesaj, Hakem, CustomUser, IlgiAlani, Degerlendirme
import re

class MakaleYuklemeForm(forms.ModelForm):
    class Meta:
        model = Makale
        fields = ['baslik', 'yazar_email', 'pdf_dosya']

    def clean_yazar_email(self):
        email = self.cleaned_data.get('yazar_email')
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            raise forms.ValidationError("Geçerli bir e-posta adresi giriniz.")
        return email

    def clean_pdf_dosya(self):
        pdf = self.cleaned_data.get('pdf_dosya')
        if pdf:
            if not pdf.name.endswith('.pdf'):
                raise forms.ValidationError("Yalnızca PDF dosyaları yükleyebilirsiniz.")
        return pdf
    

class MakaleForm(forms.ModelForm):
    class Meta:
        model = Makale
        fields = ['baslik', 'pdf_dosya']


class MakaleMesajForm(forms.ModelForm):
    class Meta:
        model = MakaleMesaj
        fields = ['icerik']
        widgets = {
            'icerik': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Mesajınızı yazın...'})
        }

class HakemOlusturForm(forms.ModelForm):
    ilgi_alanlari = forms.ModelMultipleChoiceField(
        queryset=IlgiAlani.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="İlgi Alanları"
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'email']
        labels = {
            'username': 'Kullanıcı Adı',
            'email': 'E-posta',
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'hakem'
        if commit:
            user.save()
            hakem = Hakem.objects.create(kullanici=user)
            hakem.ilgi_alanlari.set(self.cleaned_data['ilgi_alanlari'])
        return user

class DegerlendirmeForm(forms.ModelForm):
    class Meta:
        model = Degerlendirme
        fields = ['yorum', 'pdf_dosya']