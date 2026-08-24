"""洛谷查询结果模型。"""

from dataclasses import dataclass


@dataclass(slots=True)
class LuoguUserProfile:
    uid: int
    name: str
    avatar: str | None = None
    color: str | None = None
    badge: str | None = None
    slogan: str | None = None
    gu_value: int | None = None
    ranking: int | None = None
    contribution: int | None = None
    following_count: int | None = None
    follower_count: int | None = None
    passed_problem_count: int | None = None
    submitted_problem_count: int | None = None
    register_time: int | None = None
    gu_updated_at: int | None = None


@dataclass(slots=True)
class LuoguUserResult:
    ok: bool
    message: str
    profile: LuoguUserProfile | None = None


@dataclass(slots=True)
class LuoguContestProfile:
    id: int
    name: str
    start_time: int
    end_time: int
    method: int | None = None
    rated: int | None = None
    host_name: str | None = None
    problem_count: int | None = None


@dataclass(slots=True)
class LuoguContestResult:
    ok: bool
    message: str
    contests: list[LuoguContestProfile] | None = None


@dataclass(slots=True)
class LuoguSubmission:
    id: int
    uid: int
    username: str
    problem_id: str
    problem_title: str
    difficulty: int | None
    submit_time: int
    status: int
    score: int | None
    language: int | str | None
    time_ms: int | None
    memory_kb: int | None


@dataclass(slots=True)
class LuoguSubmissionResult:
    ok: bool
    message: str
    submissions: list[LuoguSubmission] | None = None
