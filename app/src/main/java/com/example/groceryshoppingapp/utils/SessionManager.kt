package com.example.groceryshoppingapp.utils
import android.content.Context
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.models.Item

import android.content.SharedPreferences
import android.util.Log
import androidx.core.content.edit
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
object SessionManager {
    private const val PREF_NAME = "GroceryAppSession"

    private const val KEY_USERNAME = "username"
    private const val KEY_ROLE = "role"
    private const val KEY_CUSTOMER_ID = "customer_id"
    private const val KEY_SHOPKEEPER_ID = "shopkeeper_id"
    private const val KEY_SHOP_ID = "shop_id"
    private const val KEY_SHOP_NAME = "shop_name"
    private const val KEY_PHOTO_BASE64 = "photo_base64"
    private const val KEY_HAS_ITEMS = "has_items_added"
    private const val KEY_AUTH_TOKEN = "auth_token"

    private const val KEY_LANGUAGE_SELECTED = "language_selected"
    private const val KEY_LANGUAGE_CODE = "language_code"

    private const val PREFS_NAME = "grocery_app_prefs"
    private const val KEY_CACHED_SHOPS = "cached_shops"
    private const val KEY_CACHED_ITEMS = "cached_items_by_shop"

    private val gson = Gson()

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)

    // --- LOGIN & ROLE ---
    fun saveLogin(context: Context, username: String, role: String) {
        Log.d("SESSION_DEBUG", "Saving login: username=$username, role=$role")
        prefs(context).edit {
            putString(KEY_USERNAME, username)
            putString(KEY_ROLE, role)
        }
    }

    // ✅ Unified auth token save/get
    fun setAuthToken(context: Context, token: String) {
        prefs(context).edit { putString(KEY_AUTH_TOKEN, token) }
    }
    fun getAuthToken(context: Context): String? = prefs(context).getString(KEY_AUTH_TOKEN, null)

    fun getUsername(context: Context): String? = prefs(context).getString(KEY_USERNAME, null)
    fun getRole(context: Context): String? = prefs(context).getString(KEY_ROLE, null)

    // --- CUSTOMER & SHOPKEEPER IDs ---
    fun setCustomerId(context: Context, id: String) = prefs(context).edit { putString(KEY_CUSTOMER_ID, id) }
    fun getCustomerId(context: Context): String? = prefs(context).getString(KEY_CUSTOMER_ID, null)

    fun setShopkeeperId(context: Context, id: String) = prefs(context).edit { putString(KEY_SHOPKEEPER_ID, id) }
    fun getShopkeeperId(context: Context): String? = prefs(context).getString(KEY_SHOPKEEPER_ID, null)

    // --- SHOP ---
    fun setShopId(context: Context, shopId: String) = prefs(context).edit { putString(KEY_SHOP_ID, shopId) }
    fun getShopId(context: Context): String? = prefs(context).getString(KEY_SHOP_ID, null)

    fun setShopInfo(context: Context, id: String?, name: String) {
        prefs(context).edit {
            putString(KEY_SHOP_ID, id)
            putString(KEY_SHOP_NAME, name)
        }
    }
    fun getShopName(context: Context): String? = prefs(context).getString(KEY_SHOP_NAME, null)




    // --- ITEMS ---
    fun setHasItemsAdded(context: Context, added: Boolean) = prefs(context).edit { putBoolean(KEY_HAS_ITEMS, added) }
    fun hasItemsAdded(context: Context): Boolean = prefs(context).getBoolean(KEY_HAS_ITEMS, false)

    // --- PROFILE ---
    fun saveUserProfile(
        context: Context,
        fullName: String,
        address: String,
        phone: String,
        email: String,
        location: String,
        photoBase64: String?
    ) {
        prefs(context).edit {
            putString("full_name", fullName)
            putString("address", address)
            putString("phone", phone)
            putString("email", email)
            putString("location", location)
            putString(KEY_PHOTO_BASE64, photoBase64)
        }
    }
    fun getPhotoBase64(context: Context): String? =
        prefs(context).getString(KEY_PHOTO_BASE64, null)?.takeIf { it.isNotBlank() && it != "null" }

    // --- LOGOUT ---
    fun logout(context: Context) {
        val langSelected = isLanguageSelected(context)
        val langCode = getLanguageCode(context)

        prefs(context).edit().clear().apply()

        // Restore language only
        setLanguageSelected(context, langSelected)
        setLanguageCode(context, langCode ?: "en")
    }

    // --- LANGUAGE ---
    fun isLanguageSelected(context: Context): Boolean = prefs(context).getBoolean(KEY_LANGUAGE_SELECTED, false)
    fun setLanguageSelected(context: Context, selected: Boolean) { prefs(context).edit { putBoolean(KEY_LANGUAGE_SELECTED, selected) } }
    fun getLanguageCode(context: Context): String? = prefs(context).getString(KEY_LANGUAGE_CODE, "en")
    fun setLanguageCode(context: Context, code: String) { prefs(context).edit { putString(KEY_LANGUAGE_CODE, code) } }

    // --- LOGIN CHECK ---
    fun isLoggedIn(context: Context): Boolean {
        val username = getUsername(context)
        val role = getRole(context)
        Log.d("SESSION_DEBUG", "Checking login: username=$username, role=$role")
        return !username.isNullOrEmpty() && !role.isNullOrEmpty()

    }


    // --- PROFILE GETTERS ---
    fun getFullName(context: Context): String? = prefs(context).getString("full_name", "")
    fun getAddress(context: Context): String? = prefs(context).getString("address", "")
    fun getPhone(context: Context): String? = prefs(context).getString("phone", "")
    fun getEmail(context: Context): String? = prefs(context).getString("email", "")
    fun getLocation(context: Context): String? = prefs(context).getString("location", "")

    // --- SHOP CHECKS ---
    fun hasShop(context: Context): Boolean = !getShopId(context).isNullOrEmpty()
    fun hasShopWithItems(context: Context): Boolean = hasShop(context) && hasItemsAdded(context)


    // ---------- Cache Shops ----------
    fun cacheShopList(context: Context, shops: List<Shop>) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val json = gson.toJson(shops)
        prefs.edit().putString(KEY_CACHED_SHOPS, json).apply()
    }

    fun getCachedShops(context: Context): List<Shop> {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val json = prefs.getString(KEY_CACHED_SHOPS, null) ?: return emptyList()
        val type = object : TypeToken<List<Shop>>() {}.type
        return gson.fromJson(json, type)
    }

    // ---------- Cache Items by Shop ----------
    fun cacheItemsByShop(context: Context, itemsByShop: Map<String, List<Item>>) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val json = gson.toJson(itemsByShop)
        prefs.edit().putString(KEY_CACHED_ITEMS, json).apply()
    }

    fun getCachedItemsByShop(context: Context): Map<String, List<Item>> {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val json = prefs.getString(KEY_CACHED_ITEMS, null) ?: return emptyMap()
        val type = object : TypeToken<Map<String, List<Item>>>() {}.type
        return gson.fromJson(json, type)
    }


}
