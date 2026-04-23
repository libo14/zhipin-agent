from __future__ import annotations

import re
from pathlib import Path

from recruitment_agents.models import CandidateProfile


SKILL_KEYWORDS = [
    "python",
    "java",
    "go",
    "typescript",
    "javascript",
    "react",
    "vue",
    "fastapi",
    "django",
    "flask",
    "langchain",
    "langgraph",
    "rag",
    "agent",
    "sql",
    "mysql",
    "postgresql",
    "redis",
    "docker",
    "kubernetes",
    "aws",
    "gcp",
    "azure",
    "ocr",
    "nlp",
    "llm",
    "机器学习",
    "深度学习",
    "招聘",
]


class ResumeParser:
    def parse_many(self, paths: list[str]) -> list[CandidateProfile]:
        profiles = []
        for item in paths:
            path = Path(item)
            if path.is_dir():
                for child in sorted(path.iterdir()):
                    if child.is_file():
                        profiles.append(self.parse(child))
            elif path.is_file():
                profiles.append(self.parse(path))
        return profiles

    def parse(self, path: Path) -> CandidateProfile:
        text = self.read_text(path)
        return self.extract_profile(text, path)

    def read_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix in {".docx", ".doc"}:
            return self._read_docx(path)
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
            return self._read_image(path)
        return path.read_text(encoding="utf-8", errors="ignore")

    def extract_profile(self, text: str, path: Path) -> CandidateProfile:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        email = first_match(r"[\w.\-+]+@[\w.\-]+\.\w+", text)
        phone = first_match(r"(?:\+?\d[\d\-\s]{8,}\d)", text)
        name = self._extract_name(lines, email, path)
        skills = self._extract_skills(text)
        years = self._extract_years(text)
        education = self._extract_education(text)
        company = self._extract_company(text)

        return CandidateProfile(
            name=name,
            email=email,
            phone=phone,
            skills=skills,
            years_experience=years,
            education=education,
            latest_company=company,
            source_path=str(path),
            raw_text=text,
        )

    def _read_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Reading PDF resumes requires pypdf.") from exc
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def _read_docx(self, path: Path) -> str:
        try:
            import docx
        except ImportError as exc:
            raise RuntimeError("Reading Word resumes requires python-docx.") from exc
        document = docx.Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    def _read_image(self, path: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("OCR image resumes require pillow and pytesseract.") from exc
        return pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")

    def _extract_name(self, lines: list[str], email: str | None, path: Path) -> str:
        for line in lines[:10]:
            match = re.search(r"(?:姓名|Name)[:：]?\s*([A-Za-z\u4e00-\u9fa5\s]{2,30})", line)
            if match:
                return match.group(1).strip()
        if lines:
            first = re.sub(r"[^A-Za-z\u4e00-\u9fa5\s]", "", lines[0]).strip()
            if 2 <= len(first) <= 30 and "resume" not in first.lower():
                return first
        if email:
            return email.split("@")[0]
        return path.stem

    def _extract_skills(self, text: str) -> list[str]:
        lowered = text.lower()
        found = []
        for skill in SKILL_KEYWORDS:
            if skill.lower() in lowered and skill not in found:
                found.append(skill)
        return found

    def _extract_years(self, text: str) -> float:
        patterns = [
            r"(\d+(?:\.\d+)?)\+?\s*(?:年|years?)\s*(?:经验|experience)?",
            r"(?:经验|experience)[:：]?\s*(\d+(?:\.\d+)?)\+?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return float(match.group(1))
        return 0

    def _extract_education(self, text: str) -> str:
        for keyword in ["博士", "PhD", "硕士", "Master", "本科", "Bachelor", "大专", "College"]:
            if keyword.lower() in text.lower():
                return keyword
        inferred = self._infer_education_from_school_history(text)
        if inferred:
            return inferred
        return "未知"

    def _infer_education_from_school_history(self, text: str) -> str | None:
        school_terms = ["大学", "学院", "University", "College", "Institute"]
        for line in text.splitlines():
            if not any(term.lower() in line.lower() for term in school_terms):
                continue
            dates = re.findall(r"(20\d{2})[./年-]\s*(0?[1-9]|1[0-2])", line)
            if len(dates) < 2:
                continue

            start = year_month_value(dates[0])
            end = year_month_value(dates[-1])
            duration_years = (end - start) / 12
            if duration_years >= 3.5:
                return "本科"
            if duration_years >= 2.0:
                return "大专"
        return None

    def _extract_company(self, text: str) -> str | None:
        match = re.search(r"(?:公司|Company)[:：]?\s*([^\n\r]{2,40})", text, flags=re.I)
        return match.group(1).strip() if match else None


def year_month_value(match: tuple[str, str]) -> int:
    year, month = match
    return int(year) * 12 + int(month)


def first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.I)
    return match.group(0).strip() if match else None
