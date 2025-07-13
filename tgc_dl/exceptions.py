class ParsingError(Exception):
    """Base exception for parsing errors."""

    pass


class CourseTitleNotFound(ParsingError):
    """Raised when the course title cannot be found."""

    pass


class ProfessorNameNotFound(ParsingError):
    """Raised when the professor's name cannot be found."""

    pass


class LectureIdNotFound(ParsingError):
    """Raised when a lecture ID cannot be found."""

    pass
