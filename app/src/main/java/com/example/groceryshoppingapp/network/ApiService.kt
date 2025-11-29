package com.example.groceryshoppingapp.network

import com.example.groceryshoppingapp.models.AddItemsRequest
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.CreateOrderRequest
import com.example.groceryshoppingapp.models.GenericResponse
import com.example.groceryshoppingapp.models.GetItemsResponse
import com.example.groceryshoppingapp.models.GetShopResponse
import com.example.groceryshoppingapp.models.LoginRequest
import com.example.groceryshoppingapp.models.LoginResponse
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.models.RegisterResponse
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.models.WalletActionRequest
import com.example.groceryshoppingapp.models.WalletActionResponse
import com.example.groceryshoppingapp.models.WalletBalanceResponse
import com.example.groceryshoppingapp.models.WalletTransaction
import okhttp3.ResponseBody
import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.Field
import retrofit2.http.FormUrlEncoded
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface ApiService {



    @POST("api/update_order_status")
    fun updateOrderStatusFinal(
        @Body body: Map<String, String>
    ): Call<Map<String, Any>>


    @GET("api/get_order_details/{uuid}") // TODO: CHANGED
    fun getOrderById(@Path("uuid") uuid: String): Call<Order>

    @GET("api/shops")
    fun getAllShops(): Call<List<Shop>>


    @POST("cart/add")
    @FormUrlEncoded
    fun addToCart(
        @Field("customer_id") customerId: Int,
        @Field("item_id") itemId: String
    ): Call<ApiResponse>

    @GET("cart/{customer_id}")
    fun getCartItems(@Path("customer_id") customerId: Int): Call<List<CartItem>>

    @POST("order/place")
    @FormUrlEncoded
    fun placeOrder(
        @Field("customer_id") customerId: Int,
        @Field("shop_id") shopId: Int,
        @Field("payment_mode") paymentMode: String
    ): Call<ApiResponse>

    // Original per‑shop endpoint (can still be used)
    @GET("api/get_shopkeeper_orders/shopkeeper/{shop_id}") // TODO : CHANGED
    fun getShopOrders(
        @Path("shop_id") shopId: String
    ): Call<List<Order>>


    @POST("order/{order_id}/status")
    @FormUrlEncoded
    fun updateOrderStatus(
        @Path("order_id") orderId: String,
        @Field("status") status: String,
        @Field("message") message: String? = null
    ): Call<ApiResponse>

    @GET("api/shops/shopkeeper/{shopkeeper_id}")
    fun getShopsForShopkeeper(@Path("shopkeeper_id") shopkeeperId: Int): Call<List<Shop>>


    @POST("login")
    fun login(@Body request: LoginRequest): Call<LoginResponse>

    @GET("api/get_customers_orders/customer/{customerId}") // TODO : CHANGED
    fun getCustomerOrders(
        @Path("customerId") customerId: String
    ): Call<List<Order>>


    @POST("/change_password")
    fun changePassword(
        @Body body: Map<String, String>
    ): Call<Map<String, Any>>


    @POST("/update_profile")
    fun updateProfile(@Body profileData: Map<String, String>): Call<ResponseBody>

    @GET("api/shops/{shop_id}/items")
    fun getItems(
        @Path("shop_id") shopId: String
    ): Call<GetItemsResponse>

    @POST("/shop/add_items")
    fun addItems(@Body request: AddItemsRequest): Call<ApiResponse>


    @PUT("/update_item/{item_id}")
    fun updateItem(
        @Path("item_id") itemId: String,
        @Body updateData: Map<String, String>
    ): Call<Map<String, Boolean>>

    @DELETE("/delete_item/{item_id}")
    fun deleteItem(@Path("item_id") itemId: String): Call<Map<String, Boolean>>

    @POST("send_otp")
    fun sendOtp(@Body body: Map<String, String>): Call<Map<String, String>>

    @POST("verify_otp")
    fun verifyOtp(@Body body: Map<String, String>): Call<Map<String, String>>

    @POST("register_after_otp")
    fun registerAfterOtp(@Body body: Map<String, String>): Call<RegisterResponse>

    @GET("/get_shop_by_owner")
    fun getShopByOwner(
        @Header("Authorization") authHeader: String,
        @Query("shopkeeperId") shopkeeperId: String
    ): Call<GetShopResponse>

    @POST("send_password_reset")
    fun sendPasswordReset(@Body email: String): Call<GenericResponse>

    @POST("send_password_reset_otp")
    fun sendPasswordResetOtp(@Body email: Map<String, String>): Call<GenericResponse>

    @POST("verify_password_reset_otp")
    fun verifyPasswordResetOtp(@Body data: Map<String, String>): Call<GenericResponse>

    @POST("update_password")
    fun updatePassword(@Body data: Map<String, String>): Call<GenericResponse>

    @POST("api/place_orders")  // TODO : CHANGED
    fun createOrder(@Body body: CreateOrderRequest): Call<Map<String, Any>>

    // 🔹 Verify payment endpoint
    @POST("/api/verify_payment")
    fun verifyPayment(
        @Body verifyData: Map<String, String>
    ): Call<Map<String, Any>>

    @GET("api/shops/{shop_id}")
    fun getShop(
        @Path("shop_id") shopId: String
    ): Call<Shop>

    @GET("internal-healthz")
    fun healthCheck(): Call<Map<String, String>>

    @POST("/create_shop")
    fun createShop(
        @Body request: CreateShopRequest
    ): Call<CreateShopResponse>  // no Header here, interceptor handles it


    @PATCH("api/update_order_items/{order_id}")
    fun updateOrderItems(
        @Path("order_id") orderId: String,
        @Body payload: UpdateOrderItemsRequest
    ): Call<Map<String, Any>>

    @POST("/api/register_fcm_token")
    fun registerFcmToken(@Body tokenData: Map<String, String>): Call<Map<String, Any>>


    // 🔹 Add these wallet endpoints to your existing ApiService interface
    @GET("/wallet/{user_id}")
    fun getWalletBalance(@Path("user_id") userId: String): Call<WalletBalanceResponse>

    @POST("/wallet/add")
    fun addMoney(@Body request: WalletActionRequest): Call<WalletActionResponse>

    @POST("/wallet/pay")
    fun payOrder(@Body request: WalletActionRequest): Call<WalletActionResponse>

    @POST("/wallet/refund")
    fun refundOrder(@Body request: WalletActionRequest): Call<WalletActionResponse>

    @GET("/wallet/transactions/{user_id}")
    fun getWalletTransactions(@Path("user_id") userId: String): Call<List<WalletTransaction>>


    @POST("/create_wallet_order")
    fun createWalletOrder(
        @Body request: WalletOrderRequest
    ): Call<WalletOrderResponse>

    @POST("/verify_wallet_payment")
    fun verifyWalletPayment(@Body data: WalletVerifyRequest): Call<Map<String, Any>>




    data class CreateShopRequest(
        val name: String,
        val address: String,
        val contact: String,
        val shopkeeper_id: String
    )

    data class CreateShopResponse(
        val success: Boolean,
        val message: String?,
        val shop: Shop?
    )
}

// ✅ Request data classes
data class UpdateOrderItemsRequest(
    val items: List<OrderItemPayload>
)

data class OrderItemPayload(
    val item_id: String,
    val quantity: Double,
    val price: Double,
    val comment: String
)

data class WalletOrderRequest(
    val user_id: String,
    val amount: Double
)

data class WalletOrderResponse(
    val backend_order_id: String,
    val razorpay_order_id: String
)


data class WalletVerifyRequest(
    val backend_order_id: String,
    val payment_id: String,
    val order_id: String,
    val signature: String
)
