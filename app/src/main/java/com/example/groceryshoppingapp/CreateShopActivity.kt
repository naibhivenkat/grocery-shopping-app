package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class CreateShopActivity : AppCompatActivity() {

    private lateinit var etShopName: EditText
    private lateinit var btnCreateShop: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_create_shop)

        etShopName = findViewById(R.id.etShopName)
        btnCreateShop = findViewById(R.id.btnCreateShop)

        btnCreateShop.setOnClickListener {
            val shopName = etShopName.text.toString().trim()
            if (shopName.isEmpty()) {
                Toast.makeText(this, "Enter shop name", Toast.LENGTH_SHORT).show()
            } else {
                createShop(shopName)
            }
        }
    }

    private fun createShop(shopName: String) {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        val shopkeeperId = SessionManager.getShopkeeperId(this)
        if (shopkeeperId.isNullOrEmpty()) {
            Toast.makeText(this, "Error: Shopkeeper ID missing. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        // Dummy values for now (can add UI fields later)
        val address = "Default Address"
        val contact = "0000000000"

        val request = ApiService.CreateShopRequest(
            name = shopName,
            address = address,
            contact = contact,
            shopkeeper_id = shopkeeperId
        )

        api.createShop(request)
            .enqueue(object : Callback<ApiService.CreateShopResponse> {
                override fun onResponse(
                    call: Call<ApiService.CreateShopResponse>,
                    response: Response<ApiService.CreateShopResponse>
                ) {
                    if (response.isSuccessful && response.body()?.success == true) {
                        val shop = response.body()!!.shop
                        if (shop != null) {
                            // Use your existing Shop model
                            val createdShop = Shop(
                                id = shop.id,
                                name = shop.name,
                                address = shop.address,
                                contact = shop.contact,
                                shopkeeper_id = shopkeeperId
                            )

                            // Save locally
                            SessionManager.setShopId(this@CreateShopActivity, createdShop.id)
                            SessionManager.setShopInfo(this@CreateShopActivity, createdShop.id, createdShop.name)

                            // Preserve token if available
                            val token = SessionManager.getAuthToken(this@CreateShopActivity)
                            if (!token.isNullOrEmpty()) {
                                SessionManager.setAuthToken(this@CreateShopActivity, token)
                            }

                            Toast.makeText(this@CreateShopActivity, "Shop created!", Toast.LENGTH_SHORT).show()
                            startActivity(Intent(this@CreateShopActivity, AddItemsActivity::class.java))
                            finish()
                        }
                    } else {
                        Toast.makeText(this@CreateShopActivity, "Failed to create shop", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<ApiService.CreateShopResponse>, t: Throwable) {
                    Toast.makeText(this@CreateShopActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }
}
