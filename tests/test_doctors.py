from booking.doctors import build_directory, name_words_match, norm_name, resolve_doctor
from tests.fake_bitrix import DIRECTORY_ROWS

DIRECTORY = build_directory(DIRECTORY_ROWS, "ufCrm0Doctors", "ufCrm0DoctorFio")


def test_declension_and_letters():
    assert name_words_match(norm_name("Ивановой Анне"), norm_name("Иванова Анна Сергеевна"))
    assert norm_name("Жәнна  Олеговна!") == "жанна олеговна"


def test_calendar_id_is_preferred():
    assert resolve_doctor(DIRECTORY, 101, "Иванова Анна") == (101, "Иванова Анна", None)


def test_name_and_calendar_must_match():
    calendar_id, _, error = resolve_doctor(DIRECTORY, 202, "Иванова Анна")
    assert calendar_id is None and "не совпадают" in error


def test_ambiguous_name_is_not_guessed():
    calendar_id, _, error = resolve_doctor(DIRECTORY, None, "Петров")
    assert calendar_id is None and "Уточни" in error


def test_doctor_without_calendar():
    calendar_id, _, error = resolve_doctor(DIRECTORY, None, "Сидоренко Жанна")
    assert calendar_id is None and "нет календаря" in error


def test_unknown_calendar():
    assert "справочнике" in resolve_doctor(DIRECTORY, 999, None)[2]
