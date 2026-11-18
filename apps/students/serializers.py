from rest_framework import serializers
from students.models import StudentProfile, GuardianProfile, StudentDocument
from accounts.serializers import UserSerializer

class GuardianProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuardianProfile
        fields = '__all__'

class StudentDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentDocument
        fields = '__all__'

class StudentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    guardian = GuardianProfileSerializer(read_only=True)
    class_name = serializers.CharField(source='class_level.name', read_only=True)
    section_name = serializers.CharField(source='section.name', read_only=True)

    class Meta:
        model = StudentProfile
        fields = '__all__'
