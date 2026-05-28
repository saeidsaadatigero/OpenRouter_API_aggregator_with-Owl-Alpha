```python
# OWL: Senior Python Engineer
# توضیح پایتون به صورت کوتاه

class PythonExplanation:
    """کلاسی برای نمایش توضیحات پایتون."""

    def __init__(self) -> None:
        self.description: str = (
            "پایتون یک زبان برنامه‌نویسی سطح بالا، تفسیری و همه‌منظوره است. "
            "این زبان به خاطر سینتکس ساده و خوانایی بالا محبوب شده است. "
            "پایتون در حوزه‌های مختلف از توسعه وب گرفته تا هوش مصنوعی و علم داده کاربرد فراوانی دارد. "
            "جامعه بزرگ و کتابخانه‌های متنوع آن، یکی از دلایل محبوبیت پایتون است."
        )

    def display(self) -> None:
        """نمایش توضیحات پایتون."""
        print(self.description)


if __name__ == "__main__":
    explanation = PythonExplanation()
    explanation.display()
```