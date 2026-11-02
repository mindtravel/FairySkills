"""Frames of a FairyPPT deck: LaTeX escaping, a content frame (kicker / source), the takeaway box, the title frame."""


def tex(s):
    return (str(s).replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")
            .replace("#", r"\#").replace("$", r"\$").replace("{", r"\{").replace("}", r"\}"))


def frame(title, body, source="", kicker=None):
    k = f"\\sect{{{kicker}}}\n" if kicker else ""
    s = f"\\source{{{source}}}\n" if source else "\\source{}\n"
    # \relax: a body that starts with {...} would otherwise be taken as the frame's subtitle argument and vanish
    return f"%{'-' * 60}\n{k}\\begin{{frame}}[t]{{{title}}}\\relax\n{body}\n{s}\\end{{frame}}\n"


def takeaway(t):
    return f"\\takeaway{{{t}}}"


def title_frame(title, subtitle, source="analysis/experiments.csv"):
    return ("\\begin{frame}[plain]\n\\centering\\vfill\n{\\fontsize{24}{30}\\selectfont\\bfseries " + title + "\\par}\n"
            "\\vspace{5mm}{\\large\\color{muted}" + subtitle + "\\par}\n"
            "\\vspace{8mm}{\\color{gray}由 " + tex(source) + " 自动生成\\par}\\vfill\n\\end{frame}\n")
