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
import com.google.android.material.navigation.NavigationView
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopOwnerDashboardActivity : AppCompatActivity() {

    private lateinit var drawerLayout: DrawerLayout
    private lateinit var navView: NavigationView
    private lateinit var btnOrders: Button
    private val api: ApiService by lazy { ApiClient.getApiService(this) }

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

        toolbar.setNavigationOnClickListener {
            drawerLayout.openDrawer(GravityCompat.END)
        }

        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeAsUpIndicator(R.drawable.ic_menu)

        // --- BUTTON ---
        btnOrders.setOnClickListener {
            startActivity(Intent(this, ShopOwnerMainActivity::class.java))
        }

        // --- NAV DRAWER ---
        navView.setNavigationItemSelectedListener { menuItem ->
            when (menuItem.itemId) {
                R.id.nav_view_profile -> startActivity(Intent(this, ProfileActivity::class.java))
                R.id.nav_settings -> startActivity(Intent(this, SettingsActivity::class.java))
                R.id.nav_manage_items -> startActivity(Intent(this, ManageItemsActivity::class.java))
                R.id.nav_shop_wallet ->
                    startActivity(Intent(this, ShopOwnerWalletActivity::class.java))
                R.id.nav_khata_book ->
                    // ⭐ NEW: Open Khata Book
                    startActivity(Intent(this, ShopKhataListActivity::class.java))


                R.id.nav_logout -> {
                    SessionManager.logout(this)
                    startActivity(Intent(this, LoginActivity::class.java).apply {
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                    })
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

        if (!hasShop) {
            // Try fetching shop from backend
            val shopkeeperId = SessionManager.getShopkeeperId(this)
            if (!shopkeeperId.isNullOrEmpty()) {
                fetchShopFromBackend(shopkeeperId)
            } else {
                // No shop & no shopkeeperId → force login
                startActivity(Intent(this, LoginActivity::class.java))
                finish()
            }
            return
        }

        // Check if items added; if not, go to AddItemsActivity
        if (!SessionManager.hasItemsAdded(this)) {
            startActivity(Intent(this, AddItemsActivity::class.java))
            finish()
        }
    }

    // --- FETCH SHOP ---
    private fun fetchShopFromBackend(shopkeeperId: String) {
        val token = SessionManager.getAuthToken(this)
        if (token.isNullOrEmpty()) {
            forceLogout()
            return
        }
        val authHeader = "Bearer $token"

        api.getShopByOwner(authHeader, shopkeeperId).enqueue(object : Callback<GetShopResponse> {
            override fun onResponse(call: Call<GetShopResponse>, response: Response<GetShopResponse>) {
                if (response.isSuccessful && response.body()?.shop != null) {
                    val shop = response.body()!!.shop
                    if (shop != null) {
                        SessionManager.setShopId(this@ShopOwnerDashboardActivity, shop.id)
                    }
                    if (shop != null) {
                        SessionManager.setShopInfo(this@ShopOwnerDashboardActivity, shop.id, shop.name)
                    }

                    // Check items
                    if (shop != null) {
                        checkShopItems(shop.id)
                    }
                } else {
                    // No shop found → create shop
                    startActivity(Intent(this@ShopOwnerDashboardActivity, CreateShopActivity::class.java))
                    finish()
                }
            }

            override fun onFailure(call: Call<GetShopResponse>, t: Throwable) {
                Toast.makeText(this@ShopOwnerDashboardActivity, "Error fetching shop", Toast.LENGTH_SHORT).show()
                startActivity(Intent(this@ShopOwnerDashboardActivity, CreateShopActivity::class.java))
                finish()
            }
        })
    }

    // --- CHECK ITEMS ---
    private fun checkShopItems(shopId: String) {
        val token = SessionManager.getAuthToken(this)
        if (token.isNullOrEmpty()) {
            forceLogout()
            return
        }


        api.getItems(shopId).enqueue(object : Callback<GetItemsResponse> {
            override fun onResponse(call: Call<GetItemsResponse>, response: Response<GetItemsResponse>) {
                when {
                    response.isSuccessful -> {
                        val itemsExist = response.body()?.items?.isNotEmpty() == true
                        Log.d("DashboardDebug", "Items exist? $itemsExist")

                        if (!itemsExist) {
                            // No items → redirect to AddItemsActivity
                            startActivity(Intent(this@ShopOwnerDashboardActivity, AddItemsActivity::class.java))
                            finish()
                        }
                        // else: stay on dashboard
                    }
                    response.code() == 401 -> forceLogout()
                    else -> {
                        Toast.makeText(this@ShopOwnerDashboardActivity, "Failed to fetch items", Toast.LENGTH_SHORT).show()
                        startActivity(Intent(this@ShopOwnerDashboardActivity, AddItemsActivity::class.java))
                        finish()
                    }
                }
            }

            override fun onFailure(call: Call<GetItemsResponse>, t: Throwable) {
                Toast.makeText(this@ShopOwnerDashboardActivity, "Network error fetching items", Toast.LENGTH_SHORT).show()
                startActivity(Intent(this@ShopOwnerDashboardActivity, AddItemsActivity::class.java))
                finish()
            }
        })
    }

    private fun forceLogout() {
        SessionManager.logout(this)
        startActivity(Intent(this, LoginActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        })
        finish()
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
