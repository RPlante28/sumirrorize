import { BAS, LE, LP } from "./config.js";

// App route -> Brightspace API path. ":params" are copied across and query strings are passed
// through. "{me}" and "{courses}" are filled in by the server (see lookups in index.ts).
export const jsonRoutes: Record<string, string> = {
  "/me": `${LP}/users/whoami`,
  "/profile": `${LP}/profile/myProfile`,
  "/courses": `${LP}/enrollments/myenrollments/?orgUnitTypeId=3`,
  "/calendar": `${LE}/calendar/events/myEvents/?orgUnitIdsCSV={courses}`,
  "/items": `${LE}/content/myItems/?orgUnitIdsCSV={courses}`,
  "/due": `${LE}/content/myItems/due/?orgUnitIdsCSV={courses}`,
  "/overdue": `${LE}/overdueItems/myItems?orgUnitIdsCSV={courses}`,
  "/awards": `${BAS}/issued/users/{me}/`,
  "/locker": `${LE}/locker/myLocker/`,

  "/courses/:ou/classlist": `${LE}/:ou/classlist/`,
  "/courses/:ou/groups": `${LP}/:ou/groupcategories/`,
  "/courses/:ou/updates": `${LE}/:ou/updates/myUpdates`,
  "/courses/:ou/calendar": `${LE}/:ou/calendar/events/myEvents/`,
  "/courses/:ou/announcements": `${LE}/:ou/news/`,

  "/courses/:ou/grades": `${LE}/:ou/grades/values/myGradeValues/`,
  "/courses/:ou/grades/final": `${LE}/:ou/grades/final/values/myGradeValue`,
  "/courses/:ou/grades/items": `${LE}/:ou/grades/`,
  "/courses/:ou/grades/categories": `${LE}/:ou/grades/categories/`,

  "/courses/:ou/assignments": `${LE}/:ou/dropbox/folders/`,
  "/courses/:ou/assignments/:id": `${LE}/:ou/dropbox/folders/:id`,
  "/courses/:ou/assignments/:id/submissions": `${LE}/:ou/dropbox/folders/:id/submissions/mysubmissions/`,

  "/courses/:ou/content": `${LE}/:ou/content/toc`,
  "/courses/:ou/content/progress": `${LE}/:ou/content/completions/mycount/?level=1`,
  "/courses/:ou/content/modules": `${LE}/:ou/content/root/`,
  "/courses/:ou/content/modules/:id": `${LE}/:ou/content/modules/:id/structure/`,
  "/courses/:ou/content/topics/:id": `${LE}/:ou/content/topics/:id`,

  "/courses/:ou/quizzes": `${LE}/:ou/quizzes/`,
  "/courses/:ou/quizzes/:id": `${LE}/:ou/quizzes/:id`,
  "/courses/:ou/surveys": `${LE}/:ou/surveys/`,
  "/courses/:ou/checklists": `${LE}/:ou/checklists/`,

  "/courses/:ou/discussions": `${LE}/:ou/discussions/forums/`,
  "/courses/:ou/discussions/:forum/topics": `${LE}/:ou/discussions/forums/:forum/topics/`,
  "/courses/:ou/discussions/:forum/topics/:topic/posts": `${LE}/:ou/discussions/forums/:forum/topics/:topic/posts/`,
};

export const fileRoutes: Record<string, string> = {
  "/profile/image": `${LP}/profile/myProfile/image`,
  "/courses/:ou/image": `${LP}/courses/:ou/image`,
  "/courses/:ou/announcements/:id/attachments/:file": `${LE}/:ou/news/:id/attachments/:file`,
  "/courses/:ou/assignments/:id/attachments/:file": `${LE}/:ou/dropbox/folders/:id/attachments/:file`,
  "/courses/:ou/assignments/:id/submissions/:submission/files/:file": `${LE}/:ou/dropbox/folders/:id/submissions/:submission/files/:file`,
  "/courses/:ou/content/topics/:id/file": `${LE}/:ou/content/topics/:id/file`,
};
