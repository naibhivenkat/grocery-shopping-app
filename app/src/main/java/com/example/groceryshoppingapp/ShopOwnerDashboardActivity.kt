package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.MenuItem
import android.widget.Button
import android.widget.Toast
import androidx.appcompat.app.ActionBarDrawerToggle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.GravityCompat
import androidx.drawerlayout.widget.DrawerLayout
import com.example.groceryshoppingapp.network.ApiClient
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.models.GetItemsResponse
import com.example.groceryshoppingapp.models.GetShopResponse
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import com.google.android.material.navigation.NavigationView

class ShopOwnerDashboardActivity : AppCompatActivity() {

    private lateinit var drawerLayout: DrawerLayout
    private lateinit var navView: NavigationView
    private lateinit var btnOrders: Button
    private val api: ApiService by lazy { ApiClient.apiService }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_owner_dashboard)

        drawerLayout = findViewById(R.id.drawer_layout)
        navView = findViewById(R.id.nav_view)
        btnOrders = findViewById(R.id.btn_view_orders)

        val toolbar = findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)

        val toggle = ActionBarDrawerToggle(
            this,
            drawerLayout,
            toolbar,
            R.string.navigation_drawer_open,
            R.string.navigation_drawer_close
        )
        drawerLayout.addDrawerListener(toggle)
        toggle.syncState()

        // Open right drawer when hamburger clicked
        toolbar.setNavigationOnClickListener {
            drawerLayout.openDrawer(GravityCompat.END)
        }

        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeAsUpIndicator(R.drawable.ic_menu)

        // --- BUTTONS ---
        btnOrders.setOnClickListener {
            startActivity(Intent(this, ShopOwnerMainActivity::class.java))
        }

        // --- NAV DRAWER ---
        navView.setNavigationItemSelectedListener { menuItem ->
            when (menuItem.itemId) {
                R.id.nav_view_profile -> startActivity(Intent(this, ProfileActivity::class.java))
                R.id.nav_settings -> startActivity(Intent(this, SettingsActivity::class.java))
                R.id.nav_manage_items -> startActivity(Intent(this, ManageItemsActivity::class.java))
                R.id.nav_logout -> {
                    SessionManager.logout(this)
                    val intent = Intent(this, LoginActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                    startActivity(intent)
                    finish()
                }
            }
            drawerLayout.closeDrawer(GravityCompat.END)
            true
        }
    }

    override fun onResume() {
        super.onResume()

        if (!SessionManager.isLoggedIn(this)) {
            Log.d("DashboardDebug", "Not logged in, redirecting to LoginActivity")
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val shopId = SessionManager.getShopId(this)
        val hasShop = !shopId.isNullOrEmpty()

        Log.d("DashboardDebug", "shopId = $shopId, hasShop = $hasShop")

        if (!hasShop) {
            // 🔄 NEW: Try fetching shop from backend using shopkeeperId
            val shopkeeperId = SessionManager.getShopkeeperId(this)
            if (!shopkeeperId.isNullOrEmpty()) {
                fetchShopFromBackend(shopkeeperId)
            } else {
                // If no shopkeeperId → force login
                startActivity(Intent(this, LoginActivity::class.java))
                finish()
            }
            return
        }

        // ✅ If we already have shopId, check items normally
        checkShopItems(shopId!!)
    }

    // --- NEW: Fetch items from backend to determine if AddItemsActivity is needed ---
    private fun checkShopItems(shopId: String) {
        val token = SessionManager.getAuthToken(this)

        // ✅ Minimal fix: redirect to login if token missing
        if (token.isNullOrEmpty()) {
            Log.d("DashboardDebug", "Auth token missing, redirecting to LoginActivity")
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val authHeader = "Bearer $token"
        api.getItems(authHeader, shopId).enqueue(object : Callback<GetItemsResponse> {
            override fun onResponse(call: Call<GetItemsResponse>, response: Response<GetItemsResponse>) {
                if (response.isSuccessful) {
                    val itemsExist = response.body()?.items?.isNotEmpty() == true
                    Log.d("DashboardDebug", "Items exist? $itemsExist")

                    if (!itemsExist) {
                        // No items → redirect to AddItemsActivity
                        startActivity(Intent(this@ShopOwnerDashboardActivity, AddItemsActivity::class.java))
                        finish()
                    }
                    // Else: stay on dashboard
                } else {
                    // Failed to fetch → fallback to AddItemsActivity
                    startActivity(Intent(this@ShopOwnerDashboardActivity, AddItemsActivity::class.java))
                    finish()
                }
            }

            override fun onFailure(call: Call<GetItemsResponse>, t: Throwable) {
                // Network error → fallback
                startActivity(Intent(this@ShopOwnerDashboardActivity, AddItemsActivity::class.java))
                finish()
            }
        })
    }

    // --- NEW: Fetch shop from backend using shopkeeperId ---
    private fun fetchShopFromBackend(shopkeeperId: String) {
        val token = SessionManager.getAuthToken(this)
        if (token.isNullOrEmpty()) {
            Log.d("DashboardDebug", "Auth token missing, redirecting to LoginActivity")
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val authHeader = "Bearer $token"

        api.getShopByOwner(authHeader, shopkeeperId).enqueue(object : Callback<GetShopResponse> {
            override fun onResponse(call: Call<GetShopResponse>, response: Response<GetShopResponse>) {
                if (response.isSuccessful && response.body()?.shop != null) {
                    val shop = response.body()!!.shop
                    // ✅ Save shopId to SessionManager
                    if (shop != null) {
                        SessionManager.setShopId(this@ShopOwnerDashboardActivity, shop.id)
                    }
                    if (shop != null) {
                        Log.d("DashboardDebug", "Fetched shop: ${shop.id}, ${shop.name}")
                    }

                    // Continue with item check
                    if (shop != null) {
                        checkShopItems(shop.id)
                    }
                } else {
                    Log.d("DashboardDebug", "No shop found for this owner → redirect to CreateShopActivity")
                    startActivity(Intent(this@ShopOwnerDashboardActivity, CreateShopActivity::class.java))
                    finish()
                }
            }

            override fun onFailure(call: Call<GetShopResponse>, t: Throwable) {
                Log.e("DashboardDebug", "Failed to fetch shop: ${t.message}")
                Toast.makeText(this@ShopOwnerDashboardActivity, "Error fetching shop", Toast.LENGTH_SHORT).show()
                startActivity(Intent(this@ShopOwnerDashboardActivity, CreateShopActivity::class.java))
                finish()
            }
        })
    }


    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            drawerLayout.openDrawer(GravityCompat.END)
            return true
        }
        return super.onOptionsItemSelected(item)
    }

    override fun onBackPressed() {
        if (drawerLayout.isDrawerOpen(GravityCompat.END)) {
            drawerLayout.closeDrawer(GravityCompat.END)
        } else {
            super.onBackPressed()
        }
    }
}
