from django.shortcuts import render
from django.views.decorators.http import require_GET

from .privacy import privacy_context


DOCS = {
    "felhasznalok": {
        "title": "Útmutató felhasználóknak",
        "eyebrow": "Diákoknak · tanároknak · munkatársaknak",
        "intro": "Az SZLG+ az iskolai fiókoddal azonosít, és egy helyen segít kezelni a csatlakozó alkalmazásokhoz tartozó belépést, adataidat és engedélyeidet.",
        "sections": [
            {
                "title": "Belépés és fiókváltás",
                "paragraphs": [
                    "Jelentkezz be az iskolai fiókod e-mail-címével. Használhatsz jelszót, vagy – ha korábban beállítottad – jelkulcsot. A jelkulcs lehet az eszközödön tárolt ujjlenyomat, arcfelismerés vagy biztonsági kulcs.",
                    "Ha több fiókot használsz ugyanazon az eszközön, a bejelentkezési oldalon választhatsz a megjegyzett fiókok közül, vagy a „Másik fiók használata” lehetőséggel új fiókkal léphetsz be. Elfelejtett jelszó esetén használd a bejelentkezési oldalon található jelszó-visszaállítást.",
                ],
                "bullets": [
                    "Jelkulcsot a Dashboard profilmenüjének Biztonság oldalán regisztrálhatsz, adhatsz neki nevet, vagy törölheted.",
                    "Ha a jelszavas belépés után jelkulcs-beállítási ajánlat jelenik meg, beállíthatod később is.",
                    "A jelkulcs elvesztésekor próbálj másik belépési módot; szükség esetén kérj segítséget az iskola adminisztrátorától.",
                ],
            },
            {
                "title": "Profil és iskolai adatok",
                "paragraphs": [
                    "A Profil oldalon ellenőrizheted a nevedet, e-mail-címedet, telefonszámodat, szerepköreidet és az SZLG+ által nyilvántartott iskolai csoportjaidat. A profiladatokat és csoporttagságokat az iskola kezeli; ha valami hibás vagy hiányzik, az iskola adminisztrátorához fordulj.",
                    "Az iskolai csoport (például osztály vagy szakkör) nem ugyanaz, mint az adminisztrációs jogosultsági kör. Az utóbbi kizárólag az SZLG+ adminisztrációs felületéhez ad jogosultságot, és alkalmazásoknak nem kerül továbbításra. Az alkalmazás csak akkor kap szerep- és iskolai csoportadatot, ha kéri a groups hozzáférést, és te jóváhagyod.",
                ],
            },
            {
                "title": "Címtár és csoportok",
                "paragraphs": [
                    "A Dashboard Címtár oldalán név vagy e-mail-cím alapján kereshetsz az iskola tagjai között. Normál felhasználóként a keresés a Globális beállításokban megadott iskolai e-mail-domainre korlátozódik; staff és admin fiókkal a teljes felhasználói állomány kereshető. A találat a teljes nevet, az osztályt, a tagozatot és az e-mail-címet mutatja.",
                    "A csoportos postafiókok külön, a személytalálatok után jelennek meg. Az adatlapjuk jelzi, hogy ilyen fiókról van szó, és megmutatja a hozzájuk kapcsolt címtárcsoportokat. A csoportok oldalán megtekintheted a csoport nevét, leírását, kezelőit, tagjait és a kapcsolt postafiókokat.",
                    "Bármelyik bejelentkezett felhasználó létrehozhat kézi csoportot. Az új csoport alapból nem közérdekű, ezért nem jelenik meg a böngészhető listában; kereséssel ettől még megtalálható. Csoporthoz önállóan csatlakozni nem lehet: a létrehozó és a többi csoportkezelő állítja be a tagságot.",
                    "A csoport adatlapján az E-mail-vázlat gomb Gmail-levélírást nyit, a csoporttagok címeivel a Címzett mezőben. A levél nem küldődik el automatikusan, de a címzettek egymás e-mail-címét látják. Nagyon nagy csoportnál másold ki a címzettlistát: a Gmail deep link URL-je nem korlátlan hosszúságú.",
                ],
            },
            {
                "title": "Alkalmazásengedélyek és adatvédelem",
                "paragraphs": [
                    "Amikor egy alkalmazás először kér hozzáférést, az engedélyező képernyőn ellenőrizd az alkalmazás nevét, fejlesztőjét, ellenőrzött státuszát és a kért adatokat. Csak olyan hozzáférést hagyj jóvá, amelyre számítasz.",
                    "A Dashboard profilmenüjének Alkalmazásengedélyek oldalán megtekintheted és visszavonhatod a korábbi engedélyeket. Visszavonás után az alkalmazás új SZLG+ hozzáférést már nem kap, de ez nem jelentkeztet ki automatikusan az alkalmazásból, és nem törli az ott már tárolt adatokat. Ezek ügyében magával az alkalmazás üzemeltetőjével vedd fel a kapcsolatot.",
                ],
                "bullets": [
                    "Az „Automatikus átirányítás” a korábban jóváhagyott alkalmazásnál kihagyja a fiókválasztó megerősítő oldalt.",
                    "A „Megerősítés és fiókváltás” minden új belépés előtt megerősítést és fiókválasztási lehetőséget ad.",
                    "Az SZLG+ jelszavadat soha ne add meg egy csatlakozó alkalmazásnak.",
                ],
            },
            {
                "title": "Nem látod a keresett alkalmazást?",
                "paragraphs": [
                    "A Dashboard alkalmazáscsempéit az iskola állítja be. Ha egy alkalmazás hiányzik, vagy nem tudsz belépni, keresd az iskola adminisztrátorát vagy az adott alkalmazás fejlesztőjét. Az SZLG+ önmagában nem tudja megoldani az alkalmazás saját fiókjával vagy szolgáltatásával kapcsolatos hibákat.",
                ],
            },
        ],
    },
    "adminok": {
        "title": "Útmutató SZLG+ adminisztrátoroknak",
        "eyebrow": "Fiókok · csoportok · alkalmazások",
        "intro": "Ez az útmutató az iskola SZLG+ felhasználói és alkalmazás-adminisztrációját végző munkatársaknak szól. Az alkalmazásszerver üzemeltetése külön, a SZLG+ fejlesztői útmutatóban található.",
        "sections": [
            {
                "title": "Adminfelület és hozzáférési szintek",
                "paragraphs": [
                    "A Django adminisztráció a /admin/ címen érhető el staff státuszú, a szükséges adminfelületi engedélyekkel rendelkező fiókkal. A staff státusz és a superuser jogosultság érzékeny: csak azok kapják meg, akiknek ténylegesen szükségük van az adminfelületre. A jogosultsági körök (Django Groups) az adminfelületi engedélyezést szolgálják; nem iskolai csoportok.",
                    "Az Alkalmazásaim felületen a bejelentkezett fejlesztők is regisztrálhatnak alkalmazást. A regisztráció rögzíti az OIDC beállításokat, de nem jelenti azt, hogy az iskola ellenőrizte vagy jóváhagyta az alkalmazást.",
                ],
                "bullets": [
                    "Felhasználó: e-mail, név, elérhetőségek, aktív állapot és staff/superuser jogosultság.",
                    "Diákprofil: OM-azonosító, kezdési év, szekció és tagozat.",
                    "Tanárprofil: munkatársi azonosító.",
                ],
            },
            {
                "title": "Fiókok, csoporttagságok és profilok",
                "paragraphs": [
                    "A Dashboard Címtár teendők felületén a staff/admin felhasználó kezelheti az iskolai szerepköröket, osztályokat és csoportos postafiókokat. A felhasználói adatlap adminisztrációs jogosultsági körei továbbra is különállnak az iskolai csoportoktól: Django Groups vagy user permission nem ad automatikusan iskolai csoporttagságot, és az iskolai szerepkörök sem adnak SZLG+ adminjogot.",
                    "A kézi csoport kezelői az adatlapról módosíthatják a leírást, a közérdekű jelzőt, a tagokat és további kezelőket. A tagok nem csatlakozhatnak vagy léphetnek ki önállóan. A szülőcsoport kiválasztásával hierarchiát lehet létrehozni; az OIDC kompatibilitás érdekében a kézi csoport slugját csak indokolt esetben változtasd.",
                    "A SmartGroup számított szerepjelzés; a tagozat-, szekció- és osztálycsoportok tagsága profiladatokból származik. Az osztályhoz az iskola külön osztályfőnök- és osztályfőnök-helyettes-csoportot képez. Az intézményi szerepkörök (például intézményvezető) betöltőit a címtár beállításainál kell rögzíteni.",
                ],
                "bullets": [
                    "A Közérdekű jelző csak a böngészhető csoportlistában való megjelenést szabályozza; nem hozzáférés-védelem.",
                    "A csoportos postafiókot explicit módon jelöld meg a fiók adatlapján, majd a Címtár teendők felületén kapcsold egy vagy több címtárcsoporthoz.",
                    "Az SZLG+ jogosultsági körök (Django Groups) nem kerülnek az ID token csoportclaimjeibe.",
                    "Fiók letiltásakor állítsd az aktív állapotot kikapcsoltra a törlés helyett; a jelkulcsos belépés is letiltott lesz.",
                ],
            },
            {
                "title": "Iskolai szerepkörök és adminisztrátori teendők",
                "paragraphs": [
                    "Az osztályokat a diákprofilok kezdési éve és szekciója alapján automatikusan rögzíti a címtár; adminisztrátor üres vagy jövőbeli osztályt is felvehet. Minden osztályhoz külön diák-, osztályfőnök- és osztályfőnök-helyettes-csoport tartozik. A tanári hozzárendelésekből képzett csoporttagságot nem a Django jogosultsági körök határozzák meg.",
                    "A Címtár teendők oldalon a hiányzó kötelező intézményi szerepkörök, osztályfőnökök, helyettesek és csoportos postafiók-kapcsolatok jelennek meg. Itt új intézményi szerepkört is létrehozhatsz és betöltőket rendelhetsz hozzá. A kezdeti kötelező szerepkörök: intézményvezető és intézményvezető-helyettes.",
                    "A Globális beállítások iskolai domainje határozza meg, hogy normál felhasználó milyen személyeket kereshet és adhat hozzá egy kézi csoporthoz. Staff és admin fiók bármely aktív felhasználói fiókot kiválaszthat.",
                    "Az Alkalmazásaim felületen az alkalmazás tulajdonosa kiválaszthatja a saját appjához szükséges iskolai csoportokat. Ha több csoport van kiválasztva, bármelyik kiválasztott tagság elegendő; az alkalmazásnak az ID token application_group_access claimjét kell ellenőriznie. Ez app-specifikus beállítás, nem SZLG+ adminisztrációs jogosultság.",
                ],
            },
            {
                "title": "Alkalmazások ellenőrzése és indítócsempék",
                "paragraphs": [
                    "Az adminfelületen ellenőrizd az OAuth alkalmazás regisztrációját, a tulajdonost, a pontos átirányítási URI-kat és az alkalmazásprofil nyilvános adatait. Nem staff felhasználó új alkalmazása alapértelmezésben ellenőrizetlen; staff felhasználó regisztrációja ellenőrzöttként indul. Az ellenőrzött státuszt az adminfelületen lehet módosítani. Ellenőrizetlen alkalmazásnál a felhasználók figyelmeztetést látnak.",
                    "A felhasználói Alkalmazásaim űrlap nem teszi közzé automatikusan az alkalmazást a Dashboardon. Csempe csak akkor jelenik meg az adott felhasználónak, ha az alkalmazásprofilban van „Indítási URL”, és a felhasználó már engedélyezte az alkalmazást. Az app nevét, rövid leírását, fejlesztőjét és logóját az engedélyező képernyőn is látják a felhasználók.",
                ],
                "bullets": [
                    "A rendszer Authorization Code grantot, RS256 aláírást és kötelező PKCE-t állít be; ezeket ne változtasd meg kliensenként.",
                    "Az átirányítási URI-nak pontosan egyeznie kell, élesben HTTPS-t használj.",
                    "A felhasználói felületen egy fiók legfeljebb 10 alkalmazást regisztrálhat; staff fiókra ez a korlát nem vonatkozik.",
                    "Kliensjelszó-cserekor a régi titok azonnal érvénytelenné válik; egyeztess az alkalmazás fejlesztőjével.",
                ],
            },
            {
                "title": "Globális adminbeállítások",
                "paragraphs": [
                    "A Globális beállítások egyetlen rekordja szabályozza a jelszavas belépés utáni jelkulcs-ajánlatot és az iskolai e-mail-domain konfigurációját. A címtár normál felhasználói keresése és a csoporttag-választó ezt a domaint használja; staff/admin keresésnél nincs domainkorlátozás. A csoportos postafiók besorolása explicit adminisztrátori jelölés, nem pusztán e-mail-cím formátumából következik.",
                    "A kiszolgáló titkait, HTTPS-t, OIDC aláírókulcsot, e-mail-küldést és adatbázist ne ezen az adminfelületen kezeld: ezek telepítési beállítások, a SZLG+ fejlesztői/üzemeltetői feladathoz tartoznak.",
                ],
            },
        ],
    },
    "alkalmazas-fejlesztok": {
        "title": "Útmutató alkalmazásfejlesztőknek",
        "eyebrow": "SZLG+ bejelentkezés a saját appodban",
        "intro": "Az SZLG+ OpenID Connect szolgáltató. Az alkalmazásod a felhasználó hitelesítését az SZLG+-ra bízza; az iskolai jelszót nem kérheti el és nem tárolhatja.",
        "sections": [
            {
                "title": "1. Regisztráld az alkalmazást",
                "paragraphs": [
                    "Jelentkezz be, majd nyisd meg az Alkalmazásaim oldalt, és válaszd az Új alkalmazás lehetőséget. Add meg a felhasználók által látott nevet, rövid leírást, fejlesztőt, opcionális logót, típust és callback URI-kat. Az alkalmazás részleteinél másold ki a kliensazonosítót és a discovery URL-t.",
                    "Válassz nyilvános klienst böngészős vagy natív mobilalkalmazáshoz (nincs kliensjelszó), bizalmas klienst pedig olyan szerveroldali alkalmazáshoz, amely biztonságosan tárolja a titkot. A bizalmas kliens titka létrehozáskor vagy forgatáskor csak egyszer látható. Tartsd szerveroldalon, és elvesztésekor egyeztetett időben forgasd.",
                ],
                "bullets": [
                    "A callback URI-k pontos egyezést igényelnek; élesben HTTPS szükséges.",
                    "Az SZLG+ Authorization Code + PKCE (S256) és RS256 beállítása rögzített.",
                    "Egy felhasználói fiók legfeljebb 10 alkalmazást regisztrálhat; ellenőrzött státuszt az iskola adminisztrátora adhat.",
                ],
            },
            {
                "title": "2. Discovery és végpontok",
                "paragraphs": [
                    "Ne kódold be saját konfigurációként az endpointokat vagy a publikus kulcsot: olvasd be az OIDC discovery dokumentumot, és az ott megadott authorization, token, userinfo, issuer és jwks_uri értékeket használd. A regisztrációs oldalon látható discovery URL az aktuális környezethez igazodik.",
                ],
                "bullets": [
                    "Éles: https://sso.szlg.info/o/.well-known/openid-configuration",
                    "Helyi SZLG+ fejlesztés: http://localhost:8002/o/.well-known/openid-configuration (csak a helyi fejlesztői környezetben).",
                    "Az éles issuer https://sso.szlg.info/o; a discovery issuer és a token iss értéke egyezzen.",
                ],
            },
            {
                "title": "3. Hitelesítsd a felhasználót szabványos OIDC-könyvtárral",
                "paragraphs": [
                    "Használj karbantartott OIDC klienskönyvtárat. Az kezeli helyesen a state-et, nonce-t, PKCE-t, tokenkérést és aláírás-ellenőrzést. Ne építs saját JWT-ellenőrzést, és ne fogadd el pusztán dekódolás alapján az ID tokent.",
                ],
                "bullets": [
                    "Kezdéskor hozz létre véletlen state-et, nonce-t és PKCE verifiert; az S256 challenge kerüljön az authorization kérésbe.",
                    "A visszatéréskor ellenőrizd a state-et, majd a kódot a token endpointon váltsd be az eredeti redirect_uri-val és PKCE verifierrel.",
                    "Ellenőrizd az ID token aláírását a discovery JWKS alapján, valamint az issuer, audience, expiry és nonce értékeket.",
                    "Az alkalmazás saját munkamenetét biztonságos, szerveroldali sessionben vagy platformos biztonságos tárolóban tartsd.",
                ],
            },
            {
                "title": "Kért scope-ok és visszakapott adatok",
                "paragraphs": [
                    "Csak a működéshez szükséges scope-okat kérd. Az openid az azonosításhoz szükséges; a groups scope iskolai szerep- és csoportadatokat is adhat. A felhasználó ezeket az engedélyező képernyőn látja, és később visszavonhatja.",
                ],
                "bullets": [
                    "openid: stabil, alkalmazásonkénti user-azonosító sub formában.",
                    "profile: név, keresztnév, vezetéknév, születési dátum.",
                    "email: e-mail-cím és email_verified; phone: telefonszám.",
                    "groups: smart_groups, manual_groups, school_groups, application_required_groups és application_group_access.",
                    "A smart_groups közé tartozhat a student, teacher, staff, part_time_student és további fióktípus-jelző. A Django adminisztrációs jogosultsági csoportokat az SZLG+ nem küldi ki.",
                ],
                "claims": [
                    {"scope": "OIDC-alap", "claim": "iss", "type": "string (URL)", "details": "Az azonosítószolgáltató issuer címe; az ID tokenen a discovery issuerével kell egyeznie."},
                    {"scope": "OIDC-alap", "claim": "aud", "type": "string vagy array<string>", "details": "A token címzettje, jellemzően a kliensazonosító. Az OIDC-könyvtár ellenőrizze, hogy a saját client_id-d szerepel benne."},
                    {"scope": "OIDC-alap", "claim": "iat", "type": "integer", "details": "A kiállítás Unix-időbélyege másodpercben."},
                    {"scope": "OIDC-alap", "claim": "exp", "type": "integer", "details": "A lejárat Unix-időbélyege másodpercben; mindig ellenőrizd."},
                    {"scope": "OIDC-alap", "claim": "nonce", "type": "string", "details": "Az authorization kérésben küldött nonce visszaigazolása; a klienskönyvtár ellenőrizze."},
                    {"scope": "openid", "claim": "sub", "type": "string (UUID)", "details": "Stabil SZLG+ tárgyazonosító. Fiókkulcsként ezt tárold; ne az e-mail-címet, és ne dolgozz fel semmilyen belső jelentést az UUID-ból."},
                    {"scope": "profile", "claim": "name", "type": "string", "details": "Teljes név; ha nincs megadva, az SZLG+ az e-mail-címet használja."},
                    {"scope": "profile", "claim": "given_name", "type": "string", "details": "Keresztnév. Üres szöveg is előfordulhat."},
                    {"scope": "profile", "claim": "family_name", "type": "string", "details": "Vezetéknév. Üres szöveg is előfordulhat."},
                    {"scope": "profile", "claim": "birthdate", "type": "string (YYYY-MM-DD)", "details": "ISO 8601 szerinti dátum; csak akkor szerepel, ha a fiókban meg van adva."},
                    {"scope": "email", "claim": "email", "type": "string", "details": "A fiók e-mail-címe."},
                    {"scope": "email", "claim": "email_verified", "type": "boolean", "details": "A cím megerősítettsége; a false értéket ne kezeld hiányzóként."},
                    {"scope": "phone", "claim": "phone_number", "type": "string", "details": "Telefonszám; üres profilmező esetén a claim kimarad."},
                    {"scope": "groups", "claim": "smart_groups", "type": "object<string, boolean>", "details": "A következő kártyákon felsorolt hét számított jelző; az értékek false esetén is szerepelnek."},
                    {"scope": "groups", "claim": "manual_groups", "type": "array<string>", "details": "Rendezett, egyedi, hierarchikus kézi csoportútvonalak slugokból; csoporttagság nélkül üres tömb."},
                    {"scope": "groups", "claim": "school_groups", "type": "array<string>", "details": "Stabil címtárcsoport-azonosítók: kézi, automatikus, tagozat-, szekció-, osztály- és iskolai szerepkörcsoportok."},
                    {"scope": "groups", "claim": "application_required_groups", "type": "array<string>", "details": "Az alkalmazás tulajdonosa által kiválasztott csoportazonosítók; legalább egy tagság szükséges, ha a lista nem üres."},
                    {"scope": "groups", "claim": "application_group_access", "type": "boolean", "details": "True, ha nincs csoportkövetelmény vagy a felhasználó legalább egy kiválasztott csoport tagja. Az alkalmazásnak ezt ellenőriznie kell."},
                ],
                "claim_note": "Az SZLG+ a null értékű opcionális claimet kihagyja; a hiányzó kulcsot és a false/üres értéket különböztesd meg. A Django adminisztrációs jogosultsági körök egyik csoportclaimbe sem kerülnek. A JSON-típusok a szerializált claimre vonatkoznak, nem Python- vagy adatbázistípusok.",
            },
            {
                "title": "A SmartGroupok: hét számított jelző",
                "paragraphs": [
                    "A smart_groups mindig objektum, benne az alábbi hét kulccsal és boolean értékkel. A jelzők a fiókprofilból és az iskolai e-mail-cím formátumából számolódnak, ezért változhatnak a profil javításakor. Nem kizárólagos szerepkörök, nem jogosultságok, és ne ezek alapján adj automatikus hozzáférést érzékeny adatokhoz.",
                ],
                "smart_groups": [
                    {"key": "student", "description": "Diákprofil esetén true; enélkül az iskolai domainű, .YYA vagy .YYYYA diákcím-formátum alapján true, de x. kezdetű tesztfióknál false."},
                    {"key": "teacher", "description": "A fiókhoz TeacherProfile tartozik."},
                    {"key": "staff", "description": "A Django is_staff értéke. Ez az SZLG+ felület jelzője, nem a kliensalkalmazás jogosultsága."},
                    {"key": "part_time_student", "description": "Esti tagozatos profil esetén true; enélkül az iskolai domainű, .YYAF vagy .YYYYAF e-mail-címformátum true."},
                    {"key": "computer_test_account", "description": "Az iskolai domainű, x. kezdetű címnél true, ha a helyi rész utolsó szegmense év- és szekciójelölést tartalmaz."},
                    {"key": "group_email", "description": "True, ha adminisztrátor a fiókot explicit csoportos postafiókként jelölte meg."},
                    {"key": "teacher_or_school_employee", "description": "Az iskolai domainű névformátum alapján számított jelző; TeacherProfile esetén a teacher jelző külön is true."},
                ],
                "bullets": [
                    "Példa: smart_groups.student === true; a kulcsok jelenlétére és az értékek típusára is ellenőrizz.",
                    "A groups scope nélkül egyik csoportclaim sem kerül az ID tokenbe. Az application_group_access true, ha nincs az alkalmazáshoz beállított csoportkövetelmény, vagy a felhasználó legalább egy kiválasztott csoport tagja; false esetén az alkalmazás tagadja meg a hozzáférést.",
                    "A manual_groups nem SmartGroup: kézzel kezelt iskolai tagság, például [\"studiosok\", \"studiosok/betanulok\"]. A leszármazott kiválasztásakor az ősútvonalak is benne vannak. A school_groups ezzel szemben a címtár összes csoportjának stabil azonosítóját tartalmazza; Django permission groupot egyik sem jelent.",
                    "A school_groups azonosítókat változtatás nélkül tárold: kézi csoportnál manual-<slug>, osztálycsoportnál az osztály kezdési éve és szekciója szerepel a kulcsban, intézményi szerepkörnél pedig a szerepkör slugja.",
                ],
                "code": "{\n  \"smart_groups\": {\n    \"student\": true,\n    \"teacher\": false,\n    \"staff\": false,\n    \"part_time_student\": false,\n    \"computer_test_account\": false,\n    \"group_email\": false,\n    \"teacher_or_school_employee\": false\n  },\n  \"manual_groups\": [\"studiosok\", \"studiosok/betanulok\"],\n  \"school_groups\": [\"manual-studiosok\", \"osztaly-2023-f-diakok\", \"smart-student\"],\n  \"application_required_groups\": [\"osztaly-2023-f-diakok\"],\n  \"application_group_access\": true\n}",
            },
            {
                "title": "Django-integráció lépésről lépésre",
                "paragraphs": [
                    "Az alábbi példa szerveroldali Django-webalkalmazáshoz készült. Az Authlib intézi az OIDC discoveryt, az Authorization Code folyamatot, a state/nonce ellenőrzését, a tokencserét és a PKCE S256 használatát. A példa az SZLG+-azonosságot Django sessionbe menti; nem hoz létre automatikusan Django User rekordot.",
                ],
                "bullets": [
                    "Python 3-mal és egy működő Django-projekttel indulj. A projekten legyen bekapcsolva a django.contrib.sessions és a SessionMiddleware (Django alapértelmezett beállításai).",
                ],
                "code_blocks": [
                    {"title": "Ha még nincs projekted (Linux/macOS)", "code": "python3 -m venv .venv\n. .venv/bin/activate\npython -m pip install Django Authlib\ndjango-admin startproject config .\npython manage.py startapp app\n# Add \"app\" to INSTALLED_APPS in config/settings.py\npython manage.py migrate"},
                    {"title": "Ha már van Django-projekted", "code": "python -m pip install Authlib\n# A Django-verziót és az Authlib telepített verzióját rögzítsd a projekt függőségei között."},
                ],
            },
            {
                "title": "1. Telepítsd az OIDC-klienst és regisztráld az alkalmazást",
                "paragraphs": [
                    "A projekt virtuális környezetében add hozzá az Authlibet, majd rögzítsd a tesztelt verzióját a függőségi fájlodban. Az SZLG+ Alkalmazásaim oldalán szerveroldali Django-projekthez bizalmas klienst válassz. A callback URL pontosan egyezzen a Django útvonalával, például https://app.example.hu/auth/oidc/callback/; élesben csak HTTPS-t használj.",
                    "A regisztráció után mentsd el a kliensazonosítót és a kliensjelszót. A titkot csak a szerver környezeti változóiban vagy titokkezelőjében tartsd, ne a Gitben és ne a böngészőben.",
                ],
                "code_blocks": [
                    {"title": "Függőség telepítése", "code": "python -m pip install Authlib\n# A telepített verziót rögzítsd a requirements.txt-ben."},
                    {"title": "SZLG+ beállítások", "code": "Éles discovery URL:\nhttps://sso.szlg.info/o/.well-known/openid-configuration\n\nHelyi SZLG+ fejlesztés:\nhttp://localhost:8002/o/.well-known/openid-configuration\n\nCallback URL példa:\nhttps://app.example.hu/auth/oidc/callback/"},
                ],
            },
            {
                "title": "2. Add meg a beállításokat és a titkokat",
                "paragraphs": [
                    "Az éles kliens pontos callback URL-jét másold be a regisztrációba. A scope-listában csak a szükséges adatokat kérd; a lenti minta nem kéri a csoportokat. Ha csoportadat kell, add hozzá a groups scope-ot, és tájékoztasd erről a felhasználót.",
                ],
                "code_blocks": [
                    {"title": "Fejlesztői shellben (ne commitold a valódi értékeket)", "code": "export SZLG_OIDC_CLIENT_ID='a-regisztralt-client-id'\nexport SZLG_OIDC_CLIENT_SECRET='a-szerveroldali-titok'\nexport SZLG_OIDC_DISCOVERY_URL='https://sso.szlg.info/o/.well-known/openid-configuration'"},
                    {"title": "settings.py", "code": "import os\n\nSZLG_OIDC_CLIENT_ID = os.environ[\"SZLG_OIDC_CLIENT_ID\"]\nSZLG_OIDC_CLIENT_SECRET = os.environ[\"SZLG_OIDC_CLIENT_SECRET\"]\nSZLG_OIDC_DISCOVERY_URL = os.environ.get(\n    \"SZLG_OIDC_DISCOVERY_URL\",\n    \"https://sso.szlg.info/o/.well-known/openid-configuration\",\n)"},
                ],
                "bullets": [
                    "A titok hiányakor a szolgáltatás induljon hibával; ne használj éles környezetben beégetett fejlesztői alapértéket.",
                    "A SessionMiddleware legyen a CommonMiddleware előtt, a CSRF middleware-t ne kapcsold ki. HTTPS mögött állíts be biztonságos session-cookie-t (SESSION_COOKIE_SECURE=True).",
                ],
            },
            {
                "title": "3. Regisztráld az OIDC-klienst",
                "paragraphs": [
                    "Hozz létre például oidc_client.py fájlt az alkalmazásodban. Az Authlib a discovery dokumentumból tölti be az authorization, token, UserInfo és JWKS végpontokat; az endpointokat és a publikus kulcsot ne másold be kézzel.",
                ],
                "code": "from authlib.integrations.django_client import OAuth\nfrom django.conf import settings\n\noauth = OAuth()\noauth.register(\n    name=\"szlg\",\n    client_id=settings.SZLG_OIDC_CLIENT_ID,\n    client_secret=settings.SZLG_OIDC_CLIENT_SECRET,\n    server_metadata_url=settings.SZLG_OIDC_DISCOVERY_URL,\n    client_kwargs={\n        \"scope\": \"openid profile email\",\n        \"code_challenge_method\": \"S256\",\n    },\n)",
            },
            {
                "title": "4. Készíts bejelentkezési és callback nézetet",
                "paragraphs": [
                    "A callback címet ugyanazzal a Django route-tal képezd, amelyet az SZLG+ kliensregisztrációban megadtál. A state/nonce ellenőrzést és az ID token aláírásának, issuerének, audience-ének, lejáratának ellenőrzését bízd az OIDC-kliensre; a tokent ne csak dekódold.",
                ],
                "code": "from authlib.integrations.base_client.errors import OAuthError\nfrom django.http import HttpResponseBadRequest\nfrom django.shortcuts import redirect\nfrom django.urls import reverse\nfrom django.views.decorators.http import require_GET\n\nfrom .oidc_client import oauth\n\n\n@require_GET\ndef oidc_login(request):\n    callback = request.build_absolute_uri(reverse(\"oidc_callback\"))\n    return oauth.szlg.authorize_redirect(request, callback)\n\n\n@require_GET\ndef oidc_callback(request):\n    try:\n        token = oauth.szlg.authorize_access_token(request)\n    except OAuthError:\n        return HttpResponseBadRequest(\"Az SZLG+ bejelentkezés nem sikerült.\")\n\n    userinfo = token.get(\"userinfo\")\n    if not userinfo or not userinfo.get(\"sub\"):\n        return HttpResponseBadRequest(\"Hiányzó OIDC-azonosító.\")\n\n    request.session.cycle_key()\n    # Csak a szükséges, JSON-kompatibilis adatokat tartsd meg a sessionben.\n    request.session[\"szlg_identity\"] = {\n        \"sub\": str(userinfo[\"sub\"]),\n        \"name\": userinfo.get(\"name\"),\n        \"email\": userinfo.get(\"email\"),\n        \"smart_groups\": dict(userinfo.get(\"smart_groups\", {})),\n        \"manual_groups\": list(userinfo.get(\"manual_groups\", [])),\n    }\n    return redirect(\"home\")",
                "bullets": [
                    "Ha a csoportokat nem kéred (nincs groups scope), a csoportclaim-ek hiányoznak; a minta ilyenkor üres értékekre állítja őket. Éles jogosultság-ellenőrzéshez csak validált ID tokenből dolgozz, és az application_group_access false értékét utasítsd el.",
                    "Ha az alkalmazásod csoporttagság alapján dönt a belépésről, a saját sessionödben a school_groups, application_required_groups és application_group_access claimet is kezeld; a példában csak a leggyakoribb identitásmezők szerepelnek.",
                    "Valódi Django-felhasználói bejelentkezéshez a saját User modelledben az egyedi sub alapján keresd/létrehozott felhasználót, majd a Django auth.login() függvényével nyiss munkamenetet. E-mail-cím alapján ne kapcsolj automatikusan meglévő fiókot.",
                ],
            },
            {
                "title": "5. Kösd be az URL-eket, majd teszteld a folyamatot",
                "paragraphs": [
                    "A callback útvonalnak betűre pontosan egyeznie kell az alkalmazásregisztrációval (séma, host, port, útvonal és záró perjel is). A nyitóoldalon tegyél be egy bejelentkezési hivatkozást az oidc_login útvonalra. A redirect(\"home\") sort cseréld az alkalmazásod saját, létező URL-nevére.",
                ],
                "code_blocks": [
                    {"title": "app/urls.py", "code": "from django.urls import path\nfrom . import views\n\nurlpatterns = [\n    path(\"auth/oidc/login/\", views.oidc_login, name=\"oidc_login\"),\n    path(\"auth/oidc/callback/\", views.oidc_callback, name=\"oidc_callback\"),\n]"},
                    {"title": "Projekt URL-konfiguráció", "code": "from django.urls import include, path\n\nurlpatterns = [\n    path(\"\", include(\"app.urls\")),\n]"},
                ],
                "bullets": [
                    "Futtasd a Django teszteket, majd próbálj bejelentkezni: ellenőrizd a consent oldalt, a callbacket és a saját session létrejöttét.",
                    "Ellenőrizd, hogy a sub tartós fiókkulcs, az opcionális adatok hiányozhatnak, a smart_groups értékei booleanok, a manual_groups elemei pedig teljes slug útvonalak.",
                    "Hibás state, redirect_uri, kliensjelszó vagy lejárt kód esetén ne hozz létre bejelentkezett sessiont. Élesben kezelj OAuth-hibát felhasználóbarát módon, de ne naplózz tokent, authorization code-ot vagy titkot.",
                ],
            },
            {
                "title": "Tokenek, hozzájárulás és biztonság",
                "paragraphs": [
                    "Az ID token aláírt RS256 JWT, a hozzáférési token viszont nem ID token, hanem API-erőforrás elérésére szolgáló opaque token. A tokenek alapértelmezett élettartama egy óra. Ha API-t használsz, az access tokent kezeld hozzáférési tokenként; ID tokent ne küldj API bearer tokenként.",
                    "A felhasználó tartósan megadhatja az engedélyt, beállíthat automatikus továbbirányítást vagy belépésenkénti megerősítést, illetve az SZLG+ felületén visszavonhatja az app hozzáférését. A visszavonás a későbbi SZLG+ hozzáférést vonja vissza; az alkalmazás saját munkamenetének lezárását az appnak kell kezelnie.",
                ],
                "bullets": [
                    "A sub a stabil fiókkulcs; ne e-mail-címmel azonosíts tartósan felhasználót.",
                    "Soha ne naplózz tokent, kliensjelszót, authorization code-ot vagy PKCE titkot.",
                    "A kliens titka nem kerülhet böngészőbe vagy mobilalkalmazásba; ezek nyilvános kliensek.",
                ],
            },
        ],
    },
    "szlg-fejlesztok": {
        "title": "Útmutató SZLG+ fejlesztőknek",
        "eyebrow": "Fejlesztés · kiadás · üzemeltetés",
        "intro": "Ez a fejezet a SZLG+ központi identitásszolgáltatást fejlesztő és üzemeltető csapatnak szól. A projekt Django-alapú webalkalmazás és OAuth 2.0 / OpenID Connect szolgáltató.",
        "sections": [
            {
                "title": "Helyi fejlesztés indítása",
                "paragraphs": [
                    "A projekt a gyökérkönyvtárban lévő requirements.txt fájlban rögzíti a Python-függőségeket. A Django-beállítások betöltéséhez SECRET_KEY és OIDC RSA privát kulcs szükséges; a kulcsot még a manage.py parancsok futtatása előtt készítsd el. A helyi runserver alapértelmezésben a 127.0.0.1:8002 címen indul.",
                ],
                "code": "python -m venv venv\n. venv/bin/activate\npip install -r requirements.txt\ncp .env.example .env\n# .env-ben állíts be fejlesztői értékeket, majd:\npython scripts/generate_oidc_key.py\npython -c \"from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())\"\n# a kiírt értéket másold a .env SECRET_KEY sorába\npython manage.py migrate\npython manage.py createsuperuser\npython manage.py runserver",
                "bullets": [
                    "A helyi .env-ben állítsd DEBUG=True, OIDC_ISSUER= (üres), ALLOWED_HOSTS=localhost,127.0.0.1, WEBAUTHN_RP_ID=localhost és WEBAUTHN_ORIGINS=http://localhost:8002,http://127.0.0.1:8002 értékekre.",
                    "OIDC_RSA_PRIVATE_KEY_FILE alapértelmezésben .secrets/oidc-private.pem; a privát kulcsot soha ne add hozzá a githez.",
                    "A fejlesztői issuer/discovery URL: http://localhost:8002/o/.well-known/openid-configuration.",
                ],
            },
            {
                "title": "Projektfelépítés és fontos invariánsok",
                "paragraphs": [
                    "Az api/models.py tartalmazza a felhasználó-, profil-, manual group-, SchoolClass-, InstitutionalRole-, csoportos postafiók-, jelkulcs-, alkalmazásprofil- és tartós alkalmazáskapcsolat modelleket. Az api/directory.py egyesíti a számított és kézzel kezelt címtárcsoportokat, az api/dashboard_views.py kezeli a címtárat és a Dashboardot, az api/oauth.py állítja elő az OIDC claim-eket.",
                    "A felhasználói modell egyedi (AUTH_USER_MODEL = api.CustomUser), ezért új adatbázisoknál mindig a projekt migrációival indulj. Már élesített user tábla átállítása más user modellre nem egyszerű migráció: adatkonverzió és külön terv szükséges.",
                ],
                "bullets": [
                    "A kliensprotokoll Authorization Code + kötelező PKCE (S256), RS256 ID tokennel; implicit és password grant, dinamikus kliensregisztráció és wildcards nincsenek engedélyezve.",
                    "Az OIDC sub stabil UUID. A groups scope a smart_groups, manual_groups és school_groups mellett az app-specifikus application_required_groups és application_group_access claimet is adja. Django jogosultsági csoportok nem OIDC claim-ek és nem címtárcsoportok.",
                    "A jelszavas és jelkulcsos végpontok rate limitedek. Több worker esetén közös cache szükséges ahhoz, hogy a limitek közösek legyenek.",
                ],
            },
            {
                "title": "Ellenőrzés és tesztek",
                "paragraphs": [
                    "A viselkedés- és biztonsági regressziók ellenőrzéséhez futtasd a Django rendszerellenőrzést és a teljes tesztcsomagot. Az OAuth/consent, claim-ek, WebAuthn, accountok, appregisztráció és dashboard funkciók tesztjei az api/tests.py fájlban vannak.",
                ],
                "code": "python manage.py check\npython manage.py test",
                "bullets": [
                    "Modellváltoztatás után ellenőrizd a makemigrations/migrate eredményét, és a migrációs fájlt is vizsgáld át.",
                    "OIDC-módosításnál teszteld a discovery metaadatot, aláírást, scope-korlátozást, PKCE-t, redirect URI-egyezést és jóváhagyás visszavonását.",
                    "WebAuthn-módosításnál teszteld a challenge lejáratát/egyszeri felhasználását, RP ID-t és origin-ellenőrzést.",
                ],
            },
            {
                "title": "Éles konfiguráció és kiadás",
                "paragraphs": [
                    "A .env.example mutatja a támogatott fő környezeti beállításokat. Éles környezetben DEBUG=False legyen, az ALLOWED_HOSTS csak a valódi hostokat tartalmazza, a szolgáltatás HTTPS mögött fusson, és OIDC_ISSUER karakterre pontosan egyezzen a discovery issuerrel és az ID token iss értékével. TLS-termináló proxy mögött csak megbízható proxy által felülírt X-Forwarded-Proto fejléc esetén kapcsold be a USE_X_FORWARDED_PROTO-t.",
                    "A WebAuthn RP ID-nek és origin listának egyeznie kell a nyilvános hosttal. Az OIDC RSA kulcsot és Django SECRET_KEY-t titokként kezeld, állandó tárhelyen őrizd, és mentésükről gondoskodj. Az OIDC kulcs cseréje megváltoztatja a JWKS-ben publikált kulcsot, ezért a korábbi aláírású ID tokenek ellenőrzése megszűnik.",
                    "A gyökér update parancsfájl frissíti a kódot és függőségeket, collectstaticet és migrációt futtat, majd újraindítja a systemd szolgáltatást. Éles kiadás előtt készíts adatbázismentést, ellenőrizd a migrációkat, majd nézd meg a szolgáltatás állapotát és logjait. A tényleges szolgáltatásnév és infrastruktúra eltérhet környezetenként.",
                ],
                "bullets": [
                    "SMTP-beállítás nélkül a jelszó-visszaállító levelek nem jutnak el a felhasználókhoz; DEBUG módban alapértelmezés szerint konzolra kerülnek.",
                    "Az alapértelmezett adatbázis SQLite. Több folyamatnál értékeld az éles terheléshez illő adatbázist, közös cache-t, mentést és visszaállítási próbát.",
                    "Ne generálj új OIDC kulcsot meglévő kulcs felülírásával csak azért, mert új deploy történik; ugyanazt a kulcsot használd tartósan.",
                ],
            },
        ],
    },
}

LANDING_ROLLOUT = {
    "available": [
        "Az SZLG+ projekt és a dokumentáció nyilvánosan elérhető.",
        "Az SZLG+-bejelentkezés elkészült az Igazoláskezelő alkalmazásban.",
        "Az SZLG+-bejelentkezés elkészült az FTV alkalmazásban.",
    ],
    "planned_apps": [
        "sport.szlg.info",
        "Stúdió",
        "app.szlg.info",
        "NodeWS",
        "szlg.info",
        "zsuri.szlg.info",
    ],
}


DOC_LINKS = [
    {"slug": "felhasznalok", "label": "Felhasználóknak", "name": "docs-users"},
    {"slug": "adminok", "label": "SZLG+ adminisztrátoroknak", "name": "docs-admins"},
    {
        "slug": "alkalmazas-fejlesztok",
        "label": "Alkalmazásfejlesztőknek",
        "name": "docs-app-developers",
    },
    {
        "slug": "szlg-fejlesztok",
        "label": "SZLG+ fejlesztőknek",
        "name": "docs-szlg-developers",
    },
]


@require_GET
def landing(request):
    return render(request, "portal/landing.html", {"rollout": LANDING_ROLLOUT})


@require_GET
def privacy(request):
    return render(request, "portal/privacy.html", privacy_context())


@require_GET
def docs(request, slug="felhasznalok"):
    if slug not in DOCS:
        slug = "felhasznalok"
    return render(
        request,
        "portal/docs.html",
        {"article": DOCS[slug], "active_slug": slug, "doc_links": DOC_LINKS},
    )
