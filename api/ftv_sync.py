"""
FTV Sync Utility Functions

Handles synchronization with FTV Forgatásszervező platform
"""
import logging
import requests
from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from typing import Dict, List, Optional

from .models import Osztaly, Profile, Igazolas, IgazolasTipus, FTVSyncMetadata

logger = logging.getLogger(__name__)

FTV_BASE_URL = "https://ftvapi.szlg.info/api/sync"


class FTVSyncError(Exception):
    """Custom exception for FTV sync errors"""
    pass


def ftv_to_bool(value) -> bool:
    """Convert various FTV API value types (bool/str/int) to a Python bool safely"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if not value or value.strip() == '' or value.strip() == '0':
            return False
        return value.strip().lower() in ('true', '1', 'yes')
    if isinstance(value, (int, float)):
        return bool(value) and value != 0
    return False


def get_cache_metadata(sync_type: str = 'base') -> Dict:
    """
    Get FTV sync metadata for responses.
    Uses database model for persistent tracking.
    
    Args:
        sync_type: Type of sync ('base', 'user_{user_id}', 'class_{osztaly_id}')
    
    Returns dict with last_sync_time, status, and age information.
    """
    return FTVSyncMetadata.get_metadata(sync_type)


def update_cache_metadata(sync_type: str, status: str, stats: dict = None):
    """
    Update sync metadata in database.
    
    Args:
        sync_type: Type of sync ('base', 'user_{user_id}', 'class_{osztaly_id}')
        status: 'success' or 'failed'
        stats: Optional statistics dictionary
    """
    try:
        print(f"\n{'='*60}")
        print(f"→ UPDATING metadata for '{sync_type}': status={status}")
        print(f"{'='*60}\n")
        logger.info(f"→ UPDATING metadata for '{sync_type}': status={status}")
        
        FTVSyncMetadata.update_sync(sync_type, status, stats)
        
        print(f"\n{'='*60}")
        print(f"✓ Metadata SUCCESSFULLY updated for '{sync_type}'")
        print(f"{'='*60}\n")
        logger.info(f"✓ Metadata SUCCESSFULLY updated for '{sync_type}'")
        
        result = FTVSyncMetadata.get_metadata(sync_type)
        print(f"Verification read: {result}\n")
        logger.info(f"✓ Verification read: {result}")
        return result
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"✗ FAILED to update metadata for '{sync_type}': {e}")
        print(f"{'='*60}\n")
        logger.error(f"✗ FAILED to update metadata for '{sync_type}': {e}")
        import traceback
        traceback.print_exc()
        logger.error(traceback.format_exc())
        raise


def get_ftv_headers() -> Dict[str, str]:
    """Get headers for FTV API requests"""
    token = settings.FTV_EXTERNAL_ACCESS_TOKEN
    if not token:
        print(f"❌ ERROR: FTV_EXTERNAL_ACCESS_TOKEN not configured in settings!")
        raise FTVSyncError("FTV_EXTERNAL_ACCESS_TOKEN not configured")
    
    print(f"   🔑 Using FTV token: ***{token[-10:]}***")
    
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


def fetch_ftv_base_sync(debug_performance: bool = False) -> Dict:
    """
    Fetch base sync data from FTV (classes + student users).
    
    Args:
        debug_performance: Whether to request performance data from FTV
    
    Returns:
        Dict with 'osztalyok', 'students', and optionally 'performance'
    """
    try:
        params = {}
        if debug_performance:
            params['debug-performance'] = 'true'
            
        response = requests.get(
            f"{FTV_BASE_URL}/base",
            headers=get_ftv_headers(),
            params=params,
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching FTV base sync: {str(e)}")
        raise FTVSyncError(f"Failed to fetch FTV base sync: {str(e)}")


def fetch_ftv_user_absences(user_id: int, debug_performance: bool = False) -> List[Dict]:
    """
    Fetch absences for a specific user from FTV.
    
    Args:
        user_id: The FTV user ID
        debug_performance: Whether to request performance data from FTV
    
    Returns:
        List of absence records, or dict with 'data' and 'performance' if debug enabled
    """
    try:
        params = {}
        if debug_performance:
            params['debug-performance'] = 'true'
        
        url = f"{FTV_BASE_URL}/hianyzasok/user/{user_id}"
        print(f"   📡 FTV API Request:")
        print(f"      URL: {url}")
        print(f"      Params: {params}")
        print(f"      Headers: Authorization=Bearer ***{settings.FTV_EXTERNAL_ACCESS_TOKEN[-10:] if settings.FTV_EXTERNAL_ACCESS_TOKEN else 'NOT SET'}***")
        
        response = requests.get(
            url,
            headers=get_ftv_headers(),
            params=params,
            timeout=30
        )
        
        print(f"   📡 FTV API Response:")
        print(f"      Status Code: {response.status_code}")
        print(f"      Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        print(f"      Response Length: {len(response.content)} bytes")
        
        response.raise_for_status()
        
        json_data = response.json()
        print(f"      JSON Keys: {list(json_data.keys()) if isinstance(json_data, dict) else 'list'}")
        if isinstance(json_data, list):
            print(f"      List Length: {len(json_data)}")
        elif isinstance(json_data, dict) and 'data' in json_data:
            print(f"      Data Length: {len(json_data.get('data', []))}")
        
        return json_data
    except requests.RequestException as e:
        print(f"   ✗ FTV API ERROR: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"      Response Status: {e.response.status_code}")
            print(f"      Response Body: {e.response.text[:500]}")
        logger.error(f"Error fetching FTV absences for user {user_id}: {str(e)}")
        raise FTVSyncError(f"Failed to fetch FTV user absences: {str(e)}")


def fetch_ftv_class_absences_by_year_szekcio(start_year: int, szekcio: str, debug_performance: bool = False) -> List[Dict]:
    """
    Fetch all absences for a specific class from FTV using startYear and szekcio.
    
    Args:
        start_year: The 4-digit start year (e.g., 2025)
        szekcio: The section/tagozat (e.g., 'F')
        debug_performance: Whether to request performance data from FTV
    
    Returns:
        List of absence records, or dict with 'data' and 'performance' if debug enabled
    """
    try:
        params = {
            'startYear': start_year,
            'szekcio': szekcio
        }
        if debug_performance:
            params['debug-performance'] = 'true'
        
        url = f"{FTV_BASE_URL}/hianyzasok/osztaly"
        print(f"   📡 FTV API Request (by year/szekcio):")
        print(f"      URL: {url}")
        print(f"      Params: {params}")
        print(f"      Headers: Authorization=Bearer ***{settings.FTV_EXTERNAL_ACCESS_TOKEN[-10:] if settings.FTV_EXTERNAL_ACCESS_TOKEN else 'NOT SET'}***")
        
        response = requests.get(
            url,
            headers=get_ftv_headers(),
            params=params,
            timeout=30
        )
        
        print(f"   📡 FTV API Response:")
        print(f"      Status Code: {response.status_code}")
        print(f"      Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        print(f"      Response Length: {len(response.content)} bytes")
        
        response.raise_for_status()
        
        json_data = response.json()
        print(f"      JSON Keys: {list(json_data.keys()) if isinstance(json_data, dict) else 'list'}")
        if isinstance(json_data, list):
            print(f"      List Length: {len(json_data)}")
        elif isinstance(json_data, dict) and 'data' in json_data:
            print(f"      Data Length: {len(json_data.get('data', []))}")
        
        return json_data
    except requests.RequestException as e:
        print(f"   ✗ FTV API ERROR: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"      Response Status: {e.response.status_code}")
            print(f"      Response Body: {e.response.text[:500]}")
        logger.error(f"Error fetching FTV absences for class {start_year}/{szekcio}: {str(e)}")
        raise FTVSyncError(f"Failed to fetch FTV class absences: {str(e)}")


def fetch_ftv_profile_by_email(email: str) -> Optional[Dict]:
    """
    Fetch user profile from FTV by email address.
    
    Args:
        email: The user's email address
    
    Returns:
        User profile dict with user_id, or None if not found
    """
    try:
        url = f"{FTV_BASE_URL}/profile/{email}"
        print(f"   📡 FTV Profile Request:")
        print(f"      URL: {url}")
        
        response = requests.get(
            url,
            headers=get_ftv_headers(),
            timeout=30
        )
        
        print(f"      Status: {response.status_code}")
        
        if response.status_code == 404:
            print(f"      Result: User not found (404)")
            return None
            
        response.raise_for_status()
        profile_data = response.json()
        print(f"      Result: {profile_data}")
        return profile_data
    except requests.RequestException as e:
        print(f"   ✗ FTV Profile ERROR: {str(e)}")
        logger.error(f"Error fetching FTV profile for {email}: {str(e)}")
        return None


def fetch_ftv_profile_by_email(email: str) -> Optional[Dict]:
    """Fetch user profile from FTV by email"""
    try:
        response = requests.get(
            f"{FTV_BASE_URL}/profile/{email}",
            headers=get_ftv_headers(),
            timeout=30
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching FTV profile for {email}: {str(e)}")
        return None


def sync_or_create_osztaly(ftv_osztaly: Dict) -> Osztaly:
    """
    Sync or create osztaly from FTV data.
    
    FTV uses startYear (e.g., 2023) and szekcio, we use kezdes_eve (e.g., 23) and tagozat.
    Convert 4-digit year to 2-digit format.
    """
    start_year = ftv_osztaly['startYear']
    # Convert 4-digit year to 2-digit (2023 -> 23, 2024 -> 24)
    kezdes_eve = start_year % 100
    tagozat = ftv_osztaly['szekcio']
    
    osztaly, created = Osztaly.objects.get_or_create(
        kezdes_eve=kezdes_eve,
        tagozat=tagozat
    )
    
    if created:
        logger.info(f"Created new osztaly: {osztaly}")
    
    return osztaly


def sync_or_create_user(ftv_absence: Dict, osztaly: Osztaly) -> Optional[User]:
    """
    Sync or create user from FTV absence data.
    
    Creates user, profile, and adds to class if not exists.
    """
    email = ftv_absence['diak_email']
    username = ftv_absence['diak_username']
    full_name = ftv_absence['diak_full_name']
    
    # Try to find user by email (most reliable)
    user = User.objects.filter(email=email).first()
    
    if not user:
        # Try by username
        user = User.objects.filter(username=username).first()
    
    if not user:
        # Create new user
        # Parse full name (assumes format: "Last First")
        name_parts = full_name.split(' ', 1)
        last_name = name_parts[0] if len(name_parts) > 0 else ''
        first_name = name_parts[1] if len(name_parts) > 1 else ''
        
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=f"{last_name.lower()}{first_name.lower()}123"  # Default password
        )
        logger.info(f"Created new user: {username} ({email})")
    
    # Ensure profile exists
    profile, created = Profile.objects.get_or_create(user=user)
    if created:
        logger.info(f"Created profile for user: {username}")
    
    # Add to class if not already there
    if not osztaly.tanulok.filter(id=user.id).exists():
        osztaly.tanulok.add(user)
        logger.info(f"Added {username} to class {osztaly}")
    
    return user


def parse_ftv_datetime(date_str: str, time_str: str) -> datetime:
    """Parse FTV date and time strings to datetime"""
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    time_obj = datetime.strptime(time_str, '%H:%M:%S').time()
    return datetime.combine(date_obj, time_obj)


def get_or_create_ftv_igazolas_tipus() -> IgazolasTipus:
    """Get or create the FTV igazolás tipus"""
    tipus, created = IgazolasTipus.objects.get_or_create(
        nev="Médiás Távollét",
        defaults={
            'leiras': 'Média tagozat FTV forgatáson való részvétel (automatikusan szinkronizálva)',
            'beleszamit': False,
            'iskolaerdeku': True
        }
    )
    if created:
        logger.info("Created 'Médiás Távollét' igazolás tipus")
    return tipus


def sync_ftv_absence(ftv_absence: Dict, user: User, ftv_tipus: IgazolasTipus) -> Igazolas:
    """
    Sync or update a single FTV absence record.
    
    Creates new Igazolas if not exists, updates if exists.
    """
    ftv_hianyzas_id = ftv_absence['id']
    profile = Profile.objects.get(user=user)
    
    # Parse times
    eleje = parse_ftv_datetime(ftv_absence['date'], ftv_absence['timeFrom'])
    vege = parse_ftv_datetime(ftv_absence['date'], ftv_absence['timeTo'])
    
    # Check if student edited the record - handle both boolean and string values
    student_edited = ftv_absence.get('student_edited', False)
    # Convert to boolean if it's a string or number
    if isinstance(student_edited, str):
        student_edited = student_edited.lower() in ('true', '1', 'yes')
    elif isinstance(student_edited, (int, float)):
        student_edited = bool(student_edited)
    
    diak_extra_ido_elotte = ftv_absence.get('student_extra_time_before')
    diak_extra_ido_utana = ftv_absence.get('student_extra_time_after')
    
    # Ensure these are integers or None
    if diak_extra_ido_elotte is not None:
        try:
            diak_extra_ido_elotte = int(diak_extra_ido_elotte)
        except (ValueError, TypeError):
            diak_extra_ido_elotte = None
    
    if diak_extra_ido_utana is not None:
        try:
            diak_extra_ido_utana = int(diak_extra_ido_utana)
        except (ValueError, TypeError):
            diak_extra_ido_utana = None
    
    # Ensure korrigalt is explicitly boolean
    korrigalt = bool(student_edited and (diak_extra_ido_elotte or diak_extra_ido_utana))
    
    # Többnapos forgatás mezők (lásd FTV Sync API update - Többnapos forgatások)
    ftv_forgatas_id = ftv_absence.get('forgatas_id')
    if ftv_forgatas_id is not None:
        try:
            ftv_forgatas_id = int(ftv_forgatas_id)
        except (ValueError, TypeError):
            ftv_forgatas_id = None
    
    ftv_tobbnapos = ftv_to_bool(ftv_absence.get('is_multi_day', False))
    # can_be_corrected hiánya (régebbi/egynapos rekordok) -> True, a régi viselkedés megtartásához
    ftv_korrigalhato = ftv_to_bool(ftv_absence.get('can_be_corrected', True))
    
    # Prepare megjegyzes from FTV data
    forgatas_details = ftv_absence.get('forgatas_details', {})
    ftv_forgatas_veg_datum = forgatas_details.get('end_date') or ftv_absence.get('date')
    if ftv_forgatas_veg_datum:
        try:
            ftv_forgatas_veg_datum = datetime.strptime(ftv_forgatas_veg_datum, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            ftv_forgatas_veg_datum = None
    megjegyzes_parts = []
    
    # Format: <Forgatás type>: <Forgatás name>
    if forgatas_details.get('name'):
        # Determine forgatas type from FTV data
        forgatas_type_raw = forgatas_details.get('type', 'rendes')
        
        # Map FTV types to display names
        type_mapping = {
            'rendes': 'Forgatás',
            'kacsa': 'KaCsa',
            'egyeb': 'Egyéb Hivatalos Távollét',
            'esemeny': 'Esemény'
        }
        
        forgatas_type_display = type_mapping.get(forgatas_type_raw, 'Forgatás')
        megjegyzes_parts.append(f"{forgatas_type_display}: {forgatas_details['name']}")
    
    # if forgatas_details.get('description'):
        # megjegyzes_parts.append(f"Leírás: {forgatas_details['description']}")
    # if forgatas_details.get('location_name'):
    #     megjegyzes_parts.append(f"Helyszín: {forgatas_details['location_name']}")
    if ftv_absence.get('student_edit_note'):
        megjegyzes_parts.append(f"Diák megjegyzése: {ftv_absence['student_edit_note']}")
    
    megjegyzes = "\n".join(megjegyzes_parts) if megjegyzes_parts else None
    
    # Determine allapot from FTV data (for new records only)
    # Map FTV fields to our allapot - handle various data types
    ftv_excused = ftv_absence.get('excused', False)
    ftv_unexcused = ftv_absence.get('unexcused', False)
    
    # Convert to proper boolean - handle strings, numbers, and actual booleans
    ftv_excused = ftv_to_bool(ftv_excused)
    ftv_unexcused = ftv_to_bool(ftv_unexcused)
    
    # Determine status based on FTV data (only used for NEW records)
    if ftv_excused:
        ftv_allapot = 'Elfogadva'
    elif ftv_unexcused:
        ftv_allapot = 'Elutasítva'
    else:
        ftv_allapot = 'Függőben'
    
    # Check if igazolas already exists
    try:
        igazolas = Igazolas.objects.get(ftv_hianyzas_id=ftv_hianyzas_id)
        
        # Update existing record - but DON'T change allapot if it already exists
        igazolas.eleje = eleje
        igazolas.vege = vege
        igazolas.korrigalt = bool(korrigalt)  # Ensure it's a boolean
        igazolas.diak_extra_ido_elotte = diak_extra_ido_elotte
        igazolas.diak_extra_ido_utana = diak_extra_ido_utana
        igazolas.megjegyzes_diak = megjegyzes
        igazolas.ftv_forgatas_id = ftv_forgatas_id
        igazolas.ftv_tobbnapos = ftv_tobbnapos
        igazolas.ftv_korrigalhato = ftv_korrigalhato
        igazolas.ftv_forgatas_veg_datum = ftv_forgatas_veg_datum
        # NOTE: allapot is NOT updated for existing records - teacher may have changed it locally
        igazolas.save()
        
        logger.info(f"Updated FTV igazolas #{igazolas.id} for {user.username} (status unchanged: {igazolas.allapot})")
        
    except Igazolas.DoesNotExist:
        # Create new record - set allapot from FTV data
        # Ensure all boolean fields are properly set
        try:
            igazolas = Igazolas.objects.create(
                profile=profile,
                eleje=eleje,
                vege=vege,
                tipus=ftv_tipus,
                megjegyzes_diak=megjegyzes,
                diak=False,  # Not created by student (explicitly False)
                ftv=True,  # From FTV (explicitly True)
                korrigalt=bool(korrigalt),  # Ensure it's a boolean
                diak_extra_ido_elotte=diak_extra_ido_elotte,
                diak_extra_ido_utana=diak_extra_ido_utana,
                ftv_hianyzas_id=ftv_hianyzas_id,
                ftv_forgatas_id=ftv_forgatas_id,
                ftv_tobbnapos=ftv_tobbnapos,
                ftv_korrigalhato=ftv_korrigalhato,
                ftv_forgatas_veg_datum=ftv_forgatas_veg_datum,
                allapot=ftv_allapot  # Sync status from FTV for new records only
            )
            
            logger.info(f"Created new FTV igazolas #{igazolas.id} for {user.username} with status: {ftv_allapot}")
        except Exception as create_error:
            logger.error(f"Failed to create igazolas for user {user.username}: {str(create_error)}")
            logger.error(f"Data being saved - eleje: {eleje}, vege: {vege}, korrigalt: {korrigalt} (type: {type(korrigalt)})")
            logger.error(f"Data being saved - diak_extra_ido_elotte: {diak_extra_ido_elotte} (type: {type(diak_extra_ido_elotte)})")
            logger.error(f"Data being saved - diak_extra_ido_utana: {diak_extra_ido_utana} (type: {type(diak_extra_ido_utana)})")
            raise
    
    return igazolas


def delete_obsolete_ftv_records(synced_ids: List[int], user: User = None):
    """
    Delete FTV igazolások that were not in the sync (beosztás changed).
    
    These represent students who were removed from the filming session.
    
    Args:
        synced_ids: List of FTV hiányzás IDs that were synced
        user: Optional user to limit deletion to specific user's records
    """
    if not synced_ids:
        # Delete all FTV records if none were synced
        obsolete = Igazolas.objects.filter(ftv=True)
        if user:
            obsolete = obsolete.filter(profile__user=user)
    else:
        obsolete = Igazolas.objects.filter(ftv=True).exclude(ftv_hianyzas_id__in=synced_ids)
        if user:
            obsolete = obsolete.filter(profile__user=user)
    
    count = obsolete.count()
    if count > 0:
        obsolete.delete()
        logger.info(f"Deleted {count} obsolete FTV igazolások (students removed from filming)")


def sync_user_absences_from_ftv(user: User, debug_performance: bool = False) -> Dict:
    """
    Sync absences for a specific user from FTV (optimized for /me endpoint).
    
    Args:
        user: The Django User instance to sync
        debug_performance: Whether to request and return performance data
    
    Returns:
        Dict with sync statistics and optional performance data
    """
    print(f"\n{'='*80}")
    print(f"🔄 STARTING USER FTV SYNC")
    print(f"   User: {user.username} ({user.email})")
    print(f"   Debug Performance: {debug_performance}")
    print(f"{'='*80}\n")
    
    stats = {
        'igazolasok_created': 0,
        'igazolasok_updated': 0,
        'igazolasok_deleted': 0,
        'errors': 0
    }
    
    ftv_performance = None
    synced_ftv_ids = []
    
    try:
        # Get FTV igazolás tipus
        print(f"📋 Getting or creating FTV igazolás tipus...")
        ftv_tipus = get_or_create_ftv_igazolas_tipus()
        print(f"   ✓ FTV tipus: {ftv_tipus.nev} (ID: {ftv_tipus.id})\n")
        
        # Get user's profile
        print(f"👤 Checking user profile...")
        try:
            profile = Profile.objects.get(user=user)
            print(f"   ✓ Profile found: ID={profile.id}\n")
        except Profile.DoesNotExist:
            print(f"   ⚠ No profile found, creating one...")
            logger.warning(f"No profile found for user {user.username}, creating one")
            profile = Profile.objects.create(user=user)
            print(f"   ✓ Profile created: ID={profile.id}\n")
        
        # Check if user has email
        if not user.email:
            print(f"   ✗ ERROR: User has no email address!\n")
            logger.error(f"User {user.username} has no email address - cannot sync with FTV")
            raise FTVSyncError(f"User {user.username} has no email address for FTV lookup")
        
        # Fetch user profile from FTV by email to get FTV user ID
        print(f"🌐 Fetching FTV profile by email: {user.email}")
        logger.info(f"Fetching FTV profile for user {user.username} ({user.email})...")
        try:
            ftv_profile = fetch_ftv_profile_by_email(user.email)
            if not ftv_profile:
                print(f"   ⚠ User NOT found in FTV system")
                print(f"   → Returning empty stats (user not registered in FTV)\n")
                logger.warning(f"User {user.username} ({user.email}) not found in FTV system - no absences to sync")
                # No error, just return empty stats with flag (user might not be in FTV yet)
                result = {
                    'statistics': stats,
                    'ftv_registered': False,
                    'message': 'User not registered in FTV system'
                }
                update_cache_metadata(f'user_{user.id}', 'success', stats)
                print(f"{'='*80}")
                print(f"✓ SYNC COMPLETED (user not in FTV)")
                print(f"{'='*80}\n")
                return result
            
            ftv_user_id = ftv_profile['user_id']
            print(f"   ✓ Found FTV user ID: {ftv_user_id}\n")
            logger.info(f"Found FTV user ID {ftv_user_id} for {user.username}")
            
            # Check if profile contains class information and sync it immediately
            if 'osztaly' in ftv_profile and ftv_profile['osztaly']:
                print(f"📚 Found class info in FTV profile:")
                ftv_osztaly_data = ftv_profile['osztaly']
                print(f"   → Class: {ftv_osztaly_data.get('startYear')}/{ftv_osztaly_data.get('szekcio')}")
                profile_osztaly = sync_or_create_osztaly(ftv_osztaly_data)
                print(f"   → Synced to osztaly: {profile_osztaly}")
                
                # Add user to their correct class if not already there
                if not profile_osztaly.tanulok.filter(id=user.id).exists():
                    profile_osztaly.tanulok.add(user)
                    logger.info(f"Added {user.username} to class {profile_osztaly} (from FTV profile)")
                    print(f"   ✓ User added to class {profile_osztaly}\n")
                else:
                    print(f"   ✓ User already in class {profile_osztaly}\n")
            else:
                print(f"⚠️  No class info in FTV profile - will use class from absences if available\n")
        except Exception as e:
            print(f"   ✗ ERROR fetching FTV profile: {str(e)}\n")
            logger.error(f"Failed to fetch FTV profile for {user.email}: {str(e)}")
            raise FTVSyncError(f"Failed to fetch FTV profile: {str(e)}")
        
        # Fetch absences for this user
        print(f"📥 Fetching absences from FTV API...")
        print(f"   Endpoint: {FTV_BASE_URL}/hianyzasok/user/{ftv_user_id}")
        logger.info(f"Fetching absences for user {user.username} (FTV ID: {ftv_user_id})...")
        response_data = fetch_ftv_user_absences(ftv_user_id, debug_performance)
        
        # Handle response format (could be list or dict with 'data' and 'performance')
        if isinstance(response_data, dict) and 'data' in response_data:
            ftv_absences = response_data['data']
            ftv_performance = response_data.get('performance')
            print(f"   ✓ Received {len(ftv_absences)} absence records (with performance data)")
        else:
            ftv_absences = response_data
            print(f"   ✓ Received {len(ftv_absences)} absence records")
        
        if ftv_performance:
            print(f"   📊 Performance: {ftv_performance}")
        print()
        
        # Process each absence record
        print(f"🔄 Processing {len(ftv_absences)} absence records...")
        for idx, ftv_absence in enumerate(ftv_absences, 1):
            absence_id = ftv_absence.get('id', 'unknown')
            print(f"\n   [{idx}/{len(ftv_absences)}] Processing absence ID: {absence_id}")
            try:
                with transaction.atomic():
                    # Extract and sync class information from FTV absence data
                    if 'osztaly' in ftv_absence and ftv_absence['osztaly']:
                        # FTV sends class info in absence - sync it
                        ftv_osztaly_data = ftv_absence['osztaly']
                        print(f"      → Class data: {ftv_osztaly_data.get('startYear')}/{ftv_osztaly_data.get('szekcio')}")
                        osztaly = sync_or_create_osztaly(ftv_osztaly_data)
                        print(f"      → Osztaly: {osztaly}")
                        
                        # Ensure user is in the correct class
                        sync_or_create_user(ftv_absence, osztaly)
                        print(f"      → User synced to class")
                    else:
                        # Fallback: use user's current class
                        osztaly = profile.osztalyom()
                        if not osztaly:
                            print(f"      ✗ ERROR: User has no class and absence has no class data - SKIPPING")
                            logger.warning(f"User {user.username} has no class and FTV absence {ftv_absence.get('id')} has no class data - skipping")
                            stats['errors'] += 1
                            continue
                        print(f"      → Using user's current class: {osztaly}")
                    
                    # Sync absence record
                    print(f"      → Syncing absence record...")
                    igazolas = sync_ftv_absence(ftv_absence, user, ftv_tipus)
                    synced_ftv_ids.append(ftv_absence['id'])
                    
                    # Check if it was an update or create
                    if Igazolas.objects.filter(ftv_hianyzas_id=ftv_absence['id']).count() > 1:
                        stats['igazolasok_updated'] += 1
                        print(f"      ✓ UPDATED igazolás #{igazolas.id}")
                    else:
                        stats['igazolasok_created'] += 1
                        print(f"      ✓ CREATED igazolás #{igazolas.id}")
                    
            except Exception as e:
                stats['errors'] += 1
                print(f"      ✗ ERROR: {str(e)}")
                logger.error(f"Error syncing absence {ftv_absence.get('id')} for user {user.username}: {str(e)}")
                import traceback
                traceback.print_exc()
                logger.error(traceback.format_exc())
                continue
        
        # Delete obsolete records for this user
        print(f"\n🗑️  Cleaning up obsolete records...")
        try:
            with transaction.atomic():
                obsolete_count = Igazolas.objects.filter(
                    ftv=True, 
                    profile__user=user
                ).exclude(ftv_hianyzas_id__in=synced_ftv_ids).count()
                print(f"   → Found {obsolete_count} obsolete records")
                delete_obsolete_ftv_records(synced_ftv_ids, user=user)
                stats['igazolasok_deleted'] = obsolete_count
                print(f"   ✓ Deleted {obsolete_count} obsolete records\n")
        except Exception as e:
            print(f"   ✗ ERROR cleaning up: {str(e)}\n")
            logger.error(f"Error cleaning up obsolete records for user {user.username}: {str(e)}")
        
        print(f"📊 SYNC STATISTICS:")
        print(f"   Created: {stats['igazolasok_created']}")
        print(f"   Updated: {stats['igazolasok_updated']}")
        print(f"   Deleted: {stats['igazolasok_deleted']}")
        print(f"   Errors: {stats['errors']}")
        print()
        
        logger.info(f"User sync completed for {user.username}: {stats}")
        
        # Update cache metadata
        print(f"💾 Updating cache metadata...")
        update_cache_metadata(f'user_{user.id}', 'success', stats)
        
        result = {
            'statistics': stats,
            'ftv_registered': True
        }
        if ftv_performance and debug_performance:
            result['ftv_performance'] = ftv_performance
        
        print(f"{'='*80}")
        print(f"✅ USER FTV SYNC COMPLETED SUCCESSFULLY")
        print(f"{'='*80}\n")
        
        return result
        
    except FTVSyncError as e:
        print(f"\n{'='*80}")
        print(f"❌ FTV SYNC ERROR: {str(e)}")
        print(f"{'='*80}\n")
        logger.error(f"FTV user sync failed for {user.username}: {str(e)}")
        update_cache_metadata(f'user_{user.id}', 'failed', stats)
        raise
    except Exception as e:
        print(f"\n{'='*80}")
        print(f"❌ UNEXPECTED ERROR: {str(e)}")
        print(f"{'='*80}\n")
        import traceback
        traceback.print_exc()
        logger.error(f"Unexpected error during FTV user sync for {user.username}: {str(e)}")
        update_cache_metadata(f'user_{user.id}', 'failed', stats)
        raise FTVSyncError(f"User sync failed: {str(e)}")


def sync_class_absences_from_ftv(osztaly: Osztaly, debug_performance: bool = False) -> Dict:
    """
    Sync absences for a specific class from FTV (optimized for /igazolas endpoint).
    
    Args:
        osztaly: The Osztaly instance to sync
        debug_performance: Whether to request and return performance data
    
    Returns:
        Dict with sync statistics and optional performance data
    """
    print(f"\n{'='*80}")
    print(f"🔄 STARTING CLASS FTV SYNC")
    print(f"   Class: {osztaly} (ID: {osztaly.id})")
    print(f"   Debug Performance: {debug_performance}")
    print(f"{'='*80}\n")
    
    stats = {
        'users_synced': 0,
        'igazolasok_created': 0,
        'igazolasok_updated': 0,
        'igazolasok_deleted': 0,
        'errors': 0
    }
    
    ftv_performance = None
    synced_ftv_ids = []
    
    try:
        # Get FTV igazolás tipus
        print(f"📋 Getting or creating FTV igazolás tipus...")
        ftv_tipus = get_or_create_ftv_igazolas_tipus()
        print(f"   ✓ FTV tipus: {ftv_tipus.nev} (ID: {ftv_tipus.id})\n")
        
        # Map local osztaly to FTV osztaly ID
        # FTV uses startYear (4-digit), we use kezdes_eve (2-digit)
        ftv_start_year = 2000 + osztaly.kezdes_eve  # Convert 23 -> 2023
        
        print(f"🔢 Mapping class to FTV:")
        print(f"   Local class ID: {osztaly.id}")
        print(f"   kezdes_eve: {osztaly.kezdes_eve}")
        print(f"   FTV start year: {ftv_start_year}")
        print(f"   tagozat/szekcio: {osztaly.tagozat}\n")
        
        # Fetch by startYear and szekcio (the correct method)
        print(f"📥 Fetching absences from FTV API...")
        print(f"   Endpoint: {FTV_BASE_URL}/hianyzasok/osztaly?startYear={ftv_start_year}&szekcio={osztaly.tagozat}")
        logger.info(f"Fetching absences for class {osztaly} using startYear={ftv_start_year}, szekcio={osztaly.tagozat}...")
        
        response_data = fetch_ftv_class_absences_by_year_szekcio(ftv_start_year, osztaly.tagozat, debug_performance)
        
        # Handle response format (could be list or dict with 'data' and 'performance')
        if isinstance(response_data, dict) and 'data' in response_data:
            ftv_absences = response_data['data']
            ftv_performance = response_data.get('performance')
            print(f"   ✓ Received {len(ftv_absences)} absence records (with performance data)")
        else:
            ftv_absences = response_data
            print(f"   ✓ Received {len(ftv_absences)} absence records")
        
        if ftv_performance:
            print(f"   📊 Performance: {ftv_performance}")
        print()
        
        if not ftv_absences:
            print(f"⚠️  WARNING: No absences received from FTV!")
            print(f"   This could mean:")
            print(f"   - Class {ftv_start_year}/{osztaly.tagozat} not found in FTV")
            print(f"   - No students have absences")
            print(f"   - FTV API returned empty data\n")
        
        # Track which users were synced
        synced_users = set()
        
        print(f"🔄 Processing {len(ftv_absences)} absence records...")
        for idx, ftv_absence in enumerate(ftv_absences, 1):
            absence_id = ftv_absence.get('id', 'unknown')
            print(f"\n   [{idx}/{len(ftv_absences)}] Processing absence ID: {absence_id}")
            try:
                with transaction.atomic():
                    # Sync or create user
                    print(f"      → Syncing/creating user...")
                    user = sync_or_create_user(ftv_absence, osztaly)
                    if not user:
                        print(f"      ✗ ERROR: Failed to sync/create user - SKIPPING")
                        continue
                    
                    print(f"      ✓ User: {user.username}")
                    synced_users.add(user.id)
                    
                    # Sync absence record
                    print(f"      → Syncing absence record...")
                    igazolas = sync_ftv_absence(ftv_absence, user, ftv_tipus)
                    synced_ftv_ids.append(ftv_absence['id'])
                    
                    # Check if it was an update or create
                    if Igazolas.objects.filter(ftv_hianyzas_id=ftv_absence['id']).count() > 1:
                        stats['igazolasok_updated'] += 1
                        print(f"      ✓ UPDATED igazolás #{igazolas.id}")
                    else:
                        stats['igazolasok_created'] += 1
                        print(f"      ✓ CREATED igazolás #{igazolas.id}")
                    
            except Exception as e:
                stats['errors'] += 1
                print(f"      ✗ ERROR: {str(e)}")
                logger.error(f"Error syncing absence {ftv_absence.get('id')}: {str(e)}")
                import traceback
                traceback.print_exc()
                continue
        
        stats['users_synced'] = len(synced_users)
        
        print(f"\n🗑️  Cleaning up obsolete records...")
        # Delete obsolete records for this class
        # Only delete records for users in this class
        try:
            with transaction.atomic():
                class_users = osztaly.tanulok.all()
                print(f"   → Class has {class_users.count()} students")
                obsolete_count = Igazolas.objects.filter(
                    ftv=True,
                    profile__user__in=class_users
                ).exclude(ftv_hianyzas_id__in=synced_ftv_ids).count()
                print(f"   → Found {obsolete_count} obsolete records")
                
                if obsolete_count > 0:
                    Igazolas.objects.filter(
                        ftv=True,
                        profile__user__in=class_users
                    ).exclude(ftv_hianyzas_id__in=synced_ftv_ids).delete()
                    logger.info(f"Deleted {obsolete_count} obsolete FTV igazolások for class {osztaly}")
                    print(f"   ✓ Deleted {obsolete_count} obsolete records")
                
                stats['igazolasok_deleted'] = obsolete_count
        except Exception as e:
            print(f"   ✗ ERROR cleaning up: {str(e)}")
            logger.error(f"Error cleaning up obsolete records for class {osztaly}: {str(e)}")
        
        print(f"\n📊 SYNC STATISTICS:")
        print(f"   Users synced: {stats['users_synced']}")
        print(f"   Created: {stats['igazolasok_created']}")
        print(f"   Updated: {stats['igazolasok_updated']}")
        print(f"   Deleted: {stats['igazolasok_deleted']}")
        print(f"   Errors: {stats['errors']}")
        print()
        
        logger.info(f"Class sync completed for {osztaly}: {stats}")
        
        # Update cache metadata
        print(f"💾 Updating cache metadata...")
        update_cache_metadata(f'class_{osztaly.id}', 'success', stats)
        
        result = {'statistics': stats}
        if ftv_performance and debug_performance:
            result['ftv_performance'] = ftv_performance
        
        print(f"{'='*80}")
        print(f"✅ CLASS FTV SYNC COMPLETED SUCCESSFULLY")
        print(f"{'='*80}\n")
        
        return result
        
    except FTVSyncError as e:
        print(f"\n{'='*80}")
        print(f"❌ FTV SYNC ERROR: {str(e)}")
        print(f"{'='*80}\n")
        logger.error(f"FTV class sync failed for {osztaly}: {str(e)}")
        update_cache_metadata(f'class_{osztaly.id}', 'failed', stats)
        raise
    except Exception as e:
        print(f"\n{'='*80}")
        print(f"❌ UNEXPECTED ERROR: {str(e)}")
        print(f"{'='*80}\n")
        import traceback
        traceback.print_exc()
        logger.error(f"Unexpected error during FTV class sync for {osztaly}: {str(e)}")
        update_cache_metadata(f'class_{osztaly.id}', 'failed', stats)
        raise FTVSyncError(f"Class sync failed: {str(e)}")


def sync_base_from_ftv(debug_performance: bool = False) -> Dict:
    """
    Base sync function - syncs base data from FTV (classes + students).
    This is a lightweight sync that doesn't fetch absence data.
    
    Args:
        debug_performance: Whether to request and return performance data
    
    Returns:
        Dict with sync statistics and optional performance data
    """
    stats = {
        'classes_synced': 0,
        'students_synced': 0,
        'errors': 0
    }
    
    ftv_performance = None
    
    try:
        # Fetch base sync data
        logger.info("Fetching base sync data from FTV...")
        response_data = fetch_ftv_base_sync(debug_performance)
        
        # Handle response format
        if isinstance(response_data, dict):
            ftv_osztalyok = response_data.get('osztalyok', [])
            ftv_students = response_data.get('students', [])
            ftv_performance = response_data.get('performance')
        else:
            logger.error("Unexpected response format from FTV base sync")
            raise FTVSyncError("Invalid response format from FTV")
        
        # Sync classes
        for ftv_osztaly in ftv_osztalyok:
            try:
                osztaly = sync_or_create_osztaly(ftv_osztaly)
                stats['classes_synced'] += 1
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error syncing osztaly {ftv_osztaly.get('id')}: {str(e)}")
        
        # Note: We don't sync students here as that would require absence data
        # This is intentionally lightweight
        stats['students_synced'] = len(ftv_students)
        
        logger.info(f"Base sync completed: {stats}")
        
        # Update cache metadata
        update_cache_metadata('base', 'success', stats)
        
        result = {'statistics': stats}
        if ftv_performance and debug_performance:
            result['ftv_performance'] = ftv_performance
        
        return result
        
    except FTVSyncError as e:
        logger.error(f"FTV base sync failed: {str(e)}")
        update_cache_metadata('base', 'failed', stats)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during FTV base sync: {str(e)}")
        update_cache_metadata('base', 'failed', stats)
        raise FTVSyncError(f"Base sync failed: {str(e)}")


def sync_full_from_ftv(debug_performance: bool = False) -> Dict:
    """
    Full sync - syncs base data (classes + students) AND absences for every class.

    Unlike sync_base_from_ftv (classes/students only), this also calls
    sync_class_absences_from_ftv for every Osztaly, so it produces a complete,
    up-to-date set of igazolások across the whole school - used by the
    admin "FTV Sync" button under Osztályok.

    Args:
        debug_performance: Whether to request and return performance data

    Returns:
        Dict with aggregated sync statistics and optional performance data
    """
    stats = {
        'classes_synced': 0,
        'students_synced': 0,
        'users_synced': 0,
        'igazolasok_created': 0,
        'igazolasok_updated': 0,
        'igazolasok_deleted': 0,
        'errors': 0,
    }

    ftv_performance = None

    try:
        logger.info("Starting full FTV sync (base + all class absences)...")

        # Step 1: base sync (classes + students)
        base_result = sync_base_from_ftv(debug_performance=debug_performance)
        base_stats = base_result.get('statistics', {})
        stats['classes_synced'] = base_stats.get('classes_synced', 0)
        stats['students_synced'] = base_stats.get('students_synced', 0)
        stats['errors'] += base_stats.get('errors', 0)
        if debug_performance and base_result.get('ftv_performance'):
            ftv_performance = {'base': base_result['ftv_performance']}

        # Step 2: sync absences for every class
        osztalyok = list(Osztaly.objects.all())
        class_performance = []
        for osztaly in osztalyok:
            try:
                class_result = sync_class_absences_from_ftv(osztaly, debug_performance=debug_performance)
                class_stats = class_result.get('statistics', {})
                stats['users_synced'] += class_stats.get('users_synced', 0)
                stats['igazolasok_created'] += class_stats.get('igazolasok_created', 0)
                stats['igazolasok_updated'] += class_stats.get('igazolasok_updated', 0)
                stats['igazolasok_deleted'] += class_stats.get('igazolasok_deleted', 0)
                stats['errors'] += class_stats.get('errors', 0)
                if debug_performance and class_result.get('ftv_performance'):
                    class_performance.append({'osztaly': str(osztaly), 'performance': class_result['ftv_performance']})
            except FTVSyncError as e:
                stats['errors'] += 1
                logger.error(f"Error syncing absences for class {osztaly}: {str(e)}")
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Unexpected error syncing absences for class {osztaly}: {str(e)}")

        if debug_performance and class_performance:
            ftv_performance = ftv_performance or {}
            ftv_performance['classes'] = class_performance

        logger.info(f"Full sync completed: {stats}")

        update_cache_metadata('base', 'success', stats)

        result = {'statistics': stats}
        if ftv_performance and debug_performance:
            result['ftv_performance'] = ftv_performance

        return result

    except FTVSyncError as e:
        logger.error(f"Full FTV sync failed: {str(e)}")
        update_cache_metadata('base', 'failed', stats)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during full FTV sync: {str(e)}")
        update_cache_metadata('base', 'failed', stats)
        raise FTVSyncError(f"Full sync failed: {str(e)}")
