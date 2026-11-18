from rest_framework import serializers
from academics.models import School, AcademicYear, ClassLevel, Section, Subject, SubjectTeacherAssignment
from accounts.serializers import UserSerializer

class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = '__all__'

class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = '__all__'

class SectionSerializer(serializers.ModelSerializer):
    class_level_name = serializers.CharField(source='class_level.name', read_only=True)
    class_teacher_name = serializers.CharField(source='class_teacher.get_full_name', read_only=True)

    class Meta:
        model = Section
        fields = '__all__'

class ClassLevelSerializer(serializers.ModelSerializer):
    sections = SectionSerializer(many=True, read_only=True)

    class Meta:
        model = ClassLevel
        fields = '__all__'

class SubjectSerializer(serializers.ModelSerializer):
    class_level_name = serializers.CharField(source='class_level.name', read_only=True)

    class Meta:
        model = Subject
        fields = '__all__'

class SubjectTeacherAssignmentSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    section_name = serializers.CharField(source='section.__str__', read_only=True)
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)

    class Meta:
        model = SubjectTeacherAssignment
        fields = '__all__'
