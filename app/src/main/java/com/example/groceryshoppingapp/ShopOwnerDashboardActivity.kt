package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.view.MenuItem
import android.widget.Button
import androidx.appcompat.app.ActionBarDrawerToggle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.GravityCompat
import androidx.drawerlayout.widget.DrawerLayout
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.navigation.NavigationView

class ShopOwnerDashboardActivity : AppCompatActivity() {

    private lateinit var drawerLayout: DrawerLayout
    private lateinit var navView: NavigationView
    private lateinit var btnOrders: Button

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

        // open right drawer when hamburger clicked
        toolbar.setNavigationOnClickListener {
            drawerLayout.openDrawer(GravityCompat.END)
        }

        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeAsUpIndicator(R.drawable.ic_menu)

        // --- SESSION CHECKS ---
        if (!SessionManager.isLoggedIn(this)) {
            // not logged in → redirect to Login
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val shopId = SessionManager.getShopId(this)
        val hasShop = !shopId.isNullOrEmpty()

        val hasItems = SessionManager.hasItemsAdded(this)

        if (!hasShop) {
            startActivity(Intent(this, CreateShopActivity::class.java))
            finish()
            return
        } else if (!hasItems) {
            startActivity(Intent(this, AddItemsActivity::class.java))
            finish()
            return
        }

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
