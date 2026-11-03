"""
Test du microphone pour Capri
"""
import speech_recognition as sr

print("=" * 60)
print("TEST DU MICROPHONE")
print("=" * 60)
print()

# Lister les microphones disponibles
print("Microphones disponibles :")
for index, name in enumerate(sr.Microphone.list_microphone_names()):
    print(f"  [{index}] {name}")

print()
print("Test d'écoute (parlez maintenant pendant 5 secondes)...")
print()

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True

try:
    with sr.Microphone() as source:
        print("🎤 Calibrage du bruit ambiant...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print(f"✅ Seuil d'énergie: {recognizer.energy_threshold}")
        print()
        print("🎤 Parlez maintenant...")
        
        audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
        print("✅ Audio capturé!")
        print()
        
        print("🔄 Reconnaissance en cours...")
        try:
            texte = recognizer.recognize_google(audio, language='fr-FR')
            print(f"✅ VOUS AVEZ DIT: {texte}")
        except sr.UnknownValueError:
            print("❌ Je n'ai pas compris ce que vous avez dit")
        except sr.RequestError as e:
            print(f"❌ Erreur de connexion: {e}")
            
except Exception as e:
    print(f"❌ ERREUR: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
input("Appuyez sur Entrée pour quitter...")
